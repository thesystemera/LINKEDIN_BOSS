import json
import re
import time
import atexit
import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

from src.services.base_service import SingletonService
from src.services.database import Database
from src.config import settings
from src.utils.logger import custom_print


class _GeminiMessage:
    def __init__(self, content):
        self.content = content


class _GeminiChoice:
    def __init__(self, message):
        self.message = message


class _GeminiResponse:
    def __init__(self, content, is_structured=False):
        if is_structured:
            self.choices = [_GeminiChoice(_GeminiMessage(json.dumps(content)))]
            self.structured_data = content
        else:
            self.choices = [_GeminiChoice(_GeminiMessage(content))]


@dataclass
class _PromptCache:
    name: Optional[str]          # Gemini cachedContents/... name, None = not cached (below minimum / error)
    expires_at: datetime
    tokens: int
    status: str


# Gemini 2.x takes a thinking token budget instead of a level
_THINKING_BUDGET = {"minimal": 0, "low": 1024, "medium": 4096, "high": -1}


def _sha(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    return t.strip()


def _parse_json(text: str) -> Any:
    t = _strip_fences(text)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", t, re.S)
        if m:
            return json.loads(m.group(1))
        raise


class AIService(SingletonService):
    """Gemini calls with three cost layers: exact answers from the database, a Gemini context cache for each
    stable system prompt (instructions + CV, put first so the prefix repeats), and a low thinking level."""

    def __init__(self):
        if self._initialized:
            return
        self.client = None
        self.gemini_configured = False
        self.dead_models = set()
        self.no_thinking = set()
        self.resolved = {}
        self.prompt_caches: Dict[str, _PromptCache] = {}
        self.usage = {"calls": 0, "cache_hits": 0, "prompt": 0, "cached": 0, "thinking": 0, "output": 0}
        self._db = None
        self._initialized = True

    async def initialize(self):
        if self.gemini_configured:
            return
        key = settings.load_api_key_from_file("gemini_key")
        if not key:
            custom_print("ERROR", "Gemini API key not found (.env GEMINI_API_KEY or src/keys/gemini_key.txt)")
            return
        self.client = genai.Client(api_key=key)
        self.gemini_configured = True
        atexit.register(self._release_prompt_caches)
        custom_print("AI", "AIService initialized - Gemini configured")

    def _chain(self, model_or_role: Optional[str]) -> List[str]:
        roles = settings.MODELS
        if not model_or_role:
            model_or_role = "forms"
        if model_or_role in roles:
            chain = list(roles[model_or_role])
        else:
            chain = [model_or_role]
            for role, models in roles.items():
                if model_or_role in models:
                    chain += [m for m in models if m != model_or_role]
                    break
            else:
                chain += [m for m in roles["forms"] if m != model_or_role]
        if model_or_role in self.resolved:
            chain = [self.resolved[model_or_role]] + [m for m in chain if m != self.resolved[model_or_role]]
        return [m for m in chain if m not in self.dead_models] or chain[-1:]

    # ── exact-answer cache (database) ──
    def _cache_db(self) -> Optional[Database]:
        if not settings.AI_RESULT_CACHE:
            return None
        if self._db is None or self._db.db_path != settings.DB_PATH:
            self._db = Database(settings.DB_PATH)
        return self._db

    def _result_key(self, kind: str, role: str, system: str, prompt: str, schema: Any, temperature: float, images: List[bytes] = None) -> str:
        return _sha(settings.AI_CACHE_EPOCH, kind, role, settings.MODELS.get(role, [role]), settings.THINKING_LEVEL.get(role),
                    system, prompt, schema, temperature, [hashlib.sha256(i).hexdigest() for i in images or []])

    def _cache_get(self, key: str, label: str) -> Any:
        db = self._cache_db()
        if not db:
            return None
        try:
            raw = db.ai_cache_get(key, settings.AI_CACHE_RETENTION_DAYS)
        except Exception as e:
            custom_print("WARNING", f"AI cache read failed: {str(e)[:120]}")
            return None
        if raw is None:
            return None
        self.usage["cache_hits"] += 1
        custom_print("AI_CACHE", f"♻ {label} answered from cache (no API call)")
        return json.loads(raw)

    def _cache_put(self, key: str, role: str, model: str, result: Any, usage: Dict):
        db = self._cache_db()
        if not db or result is None:
            return
        try:
            db.ai_cache_put(key, role, model, json.dumps(result, ensure_ascii=False), usage,
                            settings.AI_CACHE_RETENTION_DAYS, settings.AI_CACHE_MAX_ENTRIES)
        except Exception as e:
            custom_print("WARNING", f"AI cache write failed: {str(e)[:120]}")

    # ── Gemini context cache for the stable system prompt ──
    async def _prompt_cache(self, model: str, system: Optional[str]) -> Optional[str]:
        if not settings.AI_EXPLICIT_CACHE or not system:
            return None
        key = _sha(model, system)
        now = datetime.now(timezone.utc)
        cur = self.prompt_caches.get(key)
        if cur and cur.expires_at > now + timedelta(seconds=30):
            return cur.name
        ttl = settings.AI_EXPLICIT_CACHE_TTL_SECONDS
        try:
            tokens = int((await self.client.aio.models.count_tokens(model=model, contents=[system])).total_tokens or 0)
            if tokens < settings.AI_EXPLICIT_CACHE_MIN_TOKENS:
                self.prompt_caches[key] = _PromptCache(None, now + timedelta(seconds=ttl), tokens, "below_minimum")
                return None
            cached = await self.client.aio.caches.create(model=model, config=types.CreateCachedContentConfig(
                display_name=f"linkedin-boss-{key[:12]}", system_instruction=system,
                contents=["Stable instructions and candidate data for job applications."], ttl=f"{ttl}s"))
            expires = getattr(cached, "expire_time", None) or now + timedelta(seconds=ttl)
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            self.prompt_caches[key] = _PromptCache(cached.name, expires, tokens, "created")
            custom_print("AI_CACHE", f"Gemini context cache created on {model} ({tokens:,} tokens, {ttl // 60} min)")
            return cached.name
        except Exception as e:
            custom_print("WARNING", f"Gemini context cache unavailable on {model} ({str(e)[:120]}); relying on automatic prefix caching")
            self.prompt_caches[key] = _PromptCache(None, now + timedelta(seconds=600), 0, "error")
            return None

    def _disable_prompt_cache(self, name: str):
        for k, c in self.prompt_caches.items():
            if c.name == name:
                self.prompt_caches[k] = _PromptCache(None, datetime.now(timezone.utc) + timedelta(seconds=600), 0, "error")

    def _release_prompt_caches(self):
        names = [c.name for c in self.prompt_caches.values() if c.name]
        if not names:
            return
        try:
            client = genai.Client(api_key=settings.load_api_key_from_file("gemini_key"))
            for name in names:
                client.caches.delete(name=name)
        except Exception:
            pass

    def _thinking(self, model: str, role: str) -> Optional[types.ThinkingConfig]:
        level = settings.THINKING_LEVEL.get(role)
        if not level or model in self.no_thinking:
            return None
        if model.startswith("gemini-2."):
            budget = _THINKING_BUDGET.get(level, 1024)
            return types.ThinkingConfig(thinking_budget=128 if budget == 0 and "pro" in model else budget)
        return types.ThinkingConfig(thinking_level=level)

    def _record_usage(self, resp) -> Dict[str, int]:
        m = getattr(resp, "usage_metadata", None)
        u = {"prompt": getattr(m, "prompt_token_count", 0), "cached": getattr(m, "cached_content_token_count", 0),
             "thinking": getattr(m, "thoughts_token_count", 0), "output": getattr(m, "candidates_token_count", 0)}
        u = {k: int(v or 0) for k, v in u.items()}
        self.usage["calls"] += 1
        for k, v in u.items():
            self.usage[k] += v
        return u

    def usage_line(self) -> str:
        u = self.usage
        if not u["calls"] and not u["cache_hits"]:
            return ""
        share = u["cached"] / u["prompt"] * 100 if u["prompt"] else 0
        return (f"Gemini: {u['calls']} calls, {u['cache_hits']} answered from cache | input {u['prompt']:,} tokens "
                f"({share:.0f}% at cached rate) | thinking {u['thinking']:,} | output {u['output']:,}")

    async def _generate(self, model_or_role: str, contents: Any, base: Dict, system: Optional[str] = None):
        """Returns (response, model used, token usage)."""
        if not self.client:
            await self.initialize()
        if not self.client:
            raise RuntimeError("Gemini client not configured")
        last_err = None
        for model in self._chain(model_or_role):
            cache_name = await self._prompt_cache(model, system)
            for attempt in range(4):
                cfg = types.GenerateContentConfig(**base, thinking_config=self._thinking(model, model_or_role),
                                                  **({"cached_content": cache_name} if cache_name else {"system_instruction": system}))
                try:
                    t0 = time.time()
                    resp = await self.client.aio.models.generate_content(model=model, contents=contents, config=cfg)
                    u = self._record_usage(resp)
                    custom_print("AI_TIMING", f"⏱ {model} {time.time() - t0:.1f}s | in {u['prompt']:,} (cached {u['cached']:,}) | thinking {u['thinking']:,} | out {u['output']:,}")
                    self.resolved[model_or_role] = model
                    return resp, model, u
                except genai_errors.APIError as e:
                    code = getattr(e, "code", None) or 0
                    msg = str(e)
                    last_err = e
                    if cache_name and code in (400, 403, 404) and re.search(r"cach", msg, re.I):
                        custom_print("WARNING", f"Gemini context cache rejected ({code}) - sending the full prompt")
                        self._disable_prompt_cache(cache_name)
                        cache_name = None
                        continue
                    if code == 400 and model not in self.no_thinking and re.search(r"thinking", msg, re.I):
                        custom_print("WARNING", f"{model} rejected the thinking setting - using its default")
                        self.no_thinking.add(model)
                        continue
                    model_gone = code == 404 or (code in (400, 403) and re.search(
                        rf"(models/)?{re.escape(model)}\b.*(not found|not supported for generatecontent|deprecated|retired|no longer available|not available)|model (is )?(not found|deprecated|retired)",
                        msg, re.I))
                    if model_gone:
                        custom_print("WARNING", f"Model {model} unavailable ({code}) - trying next")
                        self.dead_models.add(model)
                        break
                    if code in (429, 500, 502, 503, 504) and attempt < 3:
                        wait = (2 ** attempt) * 4
                        custom_print("WARNING", f"Gemini {code} on {model}, retrying in {wait}s")
                        await asyncio.sleep(wait)
                        continue
                    raise
                except Exception as e:
                    last_err = e
                    if attempt < 2 and re.search(r"timeout|timed out|connection|reset", str(e), re.I):
                        await asyncio.sleep(3 * (attempt + 1))
                        continue
                    raise
        if isinstance(last_err, genai_errors.APIError) and getattr(last_err, "code", 0) != 404:
            raise last_err
        raise RuntimeError(f"No available model for '{model_or_role}' (tried {self._chain(model_or_role)}): {last_err}")

    async def structured(self, prompt: str, schema: Type[BaseModel], role: str = "forms", temperature: float = None,
                         system: str = None, images: List[bytes] = None) -> Optional[Dict[str, Any]]:
        """Put stable text (instructions, candidate data) in `system` and the per-job part in `prompt`:
        the system prompt is what Gemini caches."""
        temperature = settings.GEMINI_TEMPERATURE if temperature is None else temperature
        sys_text = ((system or "") + "\n\nOutput strictly valid JSON matching the schema.").strip()
        json_schema = schema.model_json_schema()
        key = self._result_key("structured", role, sys_text, prompt, json_schema, temperature, images)
        hit = self._cache_get(key, f"{role}/{schema.__name__}")
        if hit is not None:
            return hit
        contents: Any = prompt
        if images:
            contents = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images] + [prompt]
        custom_print("AI_INPUT", f"--- PROMPT ({role}) ---\n{prompt}\n----------------")
        try:
            base = dict(temperature=temperature, response_mime_type="application/json", response_json_schema=json_schema)
            resp, model, usage = await self._generate(role, contents, base, sys_text)
        except genai_errors.APIError as e:
            if getattr(e, "code", 0) != 400:
                raise
            custom_print("WARNING", f"Schema mode rejected ({str(e)[:120]}), retrying in plain JSON mode")
            schema_hint = json.dumps(json_schema)[:6000]
            base = dict(temperature=temperature, response_mime_type="application/json")
            resp, model, usage = await self._generate(role, contents, base, (sys_text + "\nJSON schema:\n" + schema_hint).strip())
        text = resp.text or ""
        custom_print("AI_OUTPUT", f"--- RESPONSE ---\n{text[:3000]}\n----------------")
        try:
            data = _parse_json(text)
        except Exception as e:
            custom_print("ERROR", f"Could not parse AI JSON: {str(e)[:150]}")
            return None
        try:
            result = schema.model_validate(data).model_dump()
        except Exception:
            result = data if isinstance(data, dict) else {"items": data}
        self._cache_put(key, role, model, result, usage)
        return result

    async def text(self, prompt: str, role: str = "forms", temperature: float = None, system: str = None,
                   max_tokens: int = 4096) -> str:
        temperature = settings.GEMINI_TEMPERATURE if temperature is None else temperature
        key = self._result_key("text", role, system, prompt, max_tokens, temperature)
        hit = self._cache_get(key, f"{role}/text")
        if hit is not None:
            return hit
        resp, model, usage = await self._generate(role, prompt, dict(temperature=temperature, max_output_tokens=max_tokens), system)
        out = (resp.text or "").strip()
        if out:
            self._cache_put(key, role, model, out, usage)
        return out

    async def call_gemini_structured(self, prompt: str, response_schema: Type[BaseModel], model: str,
                                     temperature: float = None, system_instruction: str = None) -> Optional[Dict[str, Any]]:
        return await self.structured(prompt, response_schema, role=model, temperature=temperature, system=system_instruction)

    async def call_gemini(self, prompt: str, system_instruction: str = None, model: str = None,
                          temperature: float = None, max_tokens: int = None) -> str:
        return await self.text(prompt, role=model or "forms", temperature=temperature, system=system_instruction,
                               max_tokens=max_tokens or 2048)

    async def generate(self, messages: list, model: str, temperature: float = None, max_tokens: int = None,
                       response_schema: Type[BaseModel] = None):
        system_instruction = next((m["content"] for m in messages if m["role"] == "system"), None)
        user_content = "\n\n".join(m["content"] for m in messages if m["role"] == "user")
        if response_schema:
            result = await self.structured(user_content, response_schema, role=model, temperature=temperature, system=system_instruction)
            return _GeminiResponse(result, is_structured=True)
        text = await self.text(user_content, role=model, temperature=temperature, system=system_instruction, max_tokens=max_tokens or 2048)
        return _GeminiResponse(text, is_structured=False)

    def list_models(self) -> List[str]:
        key = settings.load_api_key_from_file("gemini_key")
        client = genai.Client(api_key=key)
        out = []
        for m in client.models.list():
            name = m.name.split("/")[-1]
            actions = getattr(m, "supported_actions", None) or []
            if "gemini" in name and (not actions or "generateContent" in actions):
                out.append(name)
        return sorted(out)
