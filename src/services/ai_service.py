import copy
import json
import re
import time
import atexit
import base64
import asyncio
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel
from google import genai
from google.genai import types
from google.genai import errors as genai_errors

try:
    import anthropic
except ImportError:  # Claude stays unavailable until `pip install anthropic`
    anthropic = None

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


def _strict_schema(schema: Dict) -> Dict:
    """Claude's structured outputs want closed objects and no defaults; a schema it still rejects falls back to plain JSON."""
    s = copy.deepcopy(schema)

    def walk(node):
        if isinstance(node, dict):
            node.pop("default", None)
            if "properties" in node and "additionalProperties" not in node:
                node["additionalProperties"] = False
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(s)
    return s


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
    stable system prompt (instructions + CV, put first so the prefix repeats), and a low thinking level.
    Claude (settings.CLAUDE_MODELS) answers instead when Gemini is out of credit, with the same layers."""

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
        self.claude = None
        self.on_claude = False
        self.claude_usage = {"calls": 0, "prompt": 0, "cached": 0, "cache_write": 0, "output": 0, "usd": 0.0}
        self._db = None
        self._initialized = True

    async def initialize(self):
        if self.gemini_configured:
            return
        key = settings.load_api_key_from_file("gemini_key")
        if not key:
            if not self._switch_to_claude("No Gemini API key"):
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
        u, c = self.usage, self.claude_usage
        lines = []
        if u["calls"] or u["cache_hits"]:
            share = u["cached"] / u["prompt"] * 100 if u["prompt"] else 0
            lines.append(f"Gemini: {u['calls']} calls, {u['cache_hits']} answered from cache | input {u['prompt']:,} tokens "
                         f"({share:.0f}% at cached rate) | thinking {u['thinking']:,} | output {u['output']:,}")
        if c["calls"]:
            share = c["cached"] / c["prompt"] * 100 if c["prompt"] else 0
            lines.append(f"Claude: {c['calls']} calls | input {c['prompt']:,} tokens ({share:.0f}% at cached rate) | "
                         f"output {c['output']:,} | about ${c['usd']:.2f}")
        return "\n".join(lines)

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

    # ── Claude: takes over when Gemini is out of credit (AI_PROVIDER auto) or is chosen outright ──
    @staticmethod
    def _claude_key() -> Optional[str]:
        return settings.env("CLAUDE_API_KEY") or settings.env("ANTHROPIC_API_KEY")

    def _use_claude(self) -> bool:
        return settings.AI_PROVIDER == "claude" or self.on_claude

    def _switch_to_claude(self, why: str) -> bool:
        if settings.AI_PROVIDER == "gemini" or anthropic is None or not self._claude_key():
            return False
        if not self.on_claude:
            custom_print("WARNING", f"{why} - using Claude for the rest of this run")
        self.on_claude = True
        return True

    @staticmethod
    def _gemini_out_of_credit(e: Exception) -> bool:
        return isinstance(e, genai_errors.APIError) and (getattr(e, "code", 0) == 402 or bool(re.search(
            r"prepayment|credits? (are |is )?(depleted|exhausted)|billing (is )?(not enabled|disabled)", str(e), re.I)))

    @staticmethod
    def _claude_model(role: str) -> str:
        if role in settings.CLAUDE_MODELS:
            return settings.CLAUDE_MODELS[role]
        if str(role).startswith("claude-"):
            return role
        return settings.CLAUDE_MODELS["pro" if "pro" in str(role) else "forms"]  # a Gemini model name was passed

    def _record_claude_usage(self, model: str, usage) -> Dict[str, int]:
        fresh, read = int(usage.input_tokens or 0), int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        u = {"prompt": fresh + read + write, "cached": read, "cache_write": write, "output": int(usage.output_tokens or 0)}
        p_in, p_out, p_read = settings.CLAUDE_PRICES.get(model, (4.00, 20.00, 0.20))
        cu = self.claude_usage
        cu["calls"] += 1
        for k, v in u.items():
            cu[k] += v
        w = 2.0 if settings.CLAUDE_CACHE_TTL == "1h" else 1.25
        cu["usd"] += ((fresh + w * write) * p_in + read * p_read + u["output"] * p_out) / 1e6
        return u

    async def _claude(self, role: str, prompt: str, system: Optional[str], max_tokens: int,
                      json_schema: Optional[Dict] = None, images: List[bytes] = None):
        """Returns (text, model used, token usage). Thinking off and a low effort keep the cost down; the
        system prompt (instructions + CV) carries the cache breakpoint so it is billed at the cached rate."""
        if self.claude is None:
            self.claude = anthropic.AsyncAnthropic(api_key=self._claude_key(), max_retries=4)
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                "data": base64.standard_b64encode(img).decode("ascii")}} for img in images or []]
        content.append({"type": "text", "text": prompt})
        level = settings.THINKING_LEVEL.get(role, "low")
        out_cfg = {"effort": "low" if level == "minimal" else level}
        if json_schema is not None:
            out_cfg["format"] = {"type": "json_schema", "schema": json_schema}
        kw = dict(max_tokens=max_tokens, output_config=out_cfg, messages=[{"role": "user", "content": content}])
        if system:
            cc = {"type": "ephemeral", **({"ttl": "1h"} if settings.CLAUDE_CACHE_TTL == "1h" else {})}
            kw["system"] = [{"type": "text", "text": system, "cache_control": cc}]
        models = [self._claude_model(role), settings.CLAUDE_FALLBACK_MODEL]
        last_err = None
        for model in dict.fromkeys(m for m in models if m not in self.dead_models):
            # thinking off: Haiku takes "disabled", Sonnet 5.5 "between_tools"; Opus 5.5 always thinks, its effort sets how much
            thinking = {"type": "disabled"} if "haiku" in model else {"type": "between_tools"} if "sonnet" in model else None
            try:
                t0 = time.time()
                extra = {"thinking": thinking} if thinking else {"max_tokens": max_tokens + 4000}  # room for Opus's own thinking
                r = await self.claude.messages.create(model=model, **{**kw, **extra})
            except anthropic.NotFoundError as e:
                custom_print("WARNING", f"Model {model} unavailable (404) - trying next")
                self.dead_models.add(model)
                last_err = e
                continue
            u = self._record_claude_usage(model, r.usage)
            custom_print("AI_TIMING", f"⏱ {model} {time.time() - t0:.1f}s | in {u['prompt']:,} (cached {u['cached']:,}, "
                                      f"cache write {u['cache_write']:,}) | out {u['output']:,}")
            if r.stop_reason == "refusal":
                custom_print("WARNING", f"{model} declined to answer ({role})")
                return "", model, u
            return "".join(b.text for b in r.content if b.type == "text"), model, u
        raise RuntimeError(f"No available Claude model for '{role}': {last_err}")

    async def _claude_structured(self, role: str, prompt: str, json_schema: Dict, sys_text: str, images: List[bytes] = None):
        try:
            return await self._claude(role, prompt, sys_text, 8192, _strict_schema(json_schema), images)
        except anthropic.BadRequestError as e:
            if not re.search(r"schema|format|grammar|output_config", str(e), re.I):
                raise
            custom_print("WARNING", f"Claude rejected the schema ({str(e)[:160]}), retrying in plain JSON mode")
            hint = (sys_text + "\nJSON schema:\n" + json.dumps(json_schema)[:6000]).strip()
            return await self._claude(role, prompt, hint, 8192, None, images)

    async def _gemini_structured(self, role: str, prompt: str, json_schema: Dict, sys_text: str, temperature: float,
                                 images: List[bytes] = None):
        contents: Any = prompt
        if images:
            contents = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images] + [prompt]
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
        return resp.text or "", model, usage

    async def _route(self, gemini_call, claude_call):
        """Gemini unless Claude is in use; a Gemini credit failure moves this and every later call to Claude."""
        if not self._use_claude():
            if not self.client:
                await self.initialize()
            if not self._use_claude():
                try:
                    return await gemini_call()
                except Exception as e:
                    if not (self._gemini_out_of_credit(e) and self._switch_to_claude(f"Gemini is out of credit ({getattr(e, 'code', '')})")):
                        raise
        return await claude_call()

    async def structured(self, prompt: str, schema: Type[BaseModel], role: str = "forms", temperature: float = None,
                         system: str = None, images: List[bytes] = None) -> Optional[Dict[str, Any]]:
        """Put stable text (instructions, candidate data) in `system` and the per-job part in `prompt`:
        the system prompt is what Gemini and Claude cache."""
        temperature = settings.GEMINI_TEMPERATURE if temperature is None else temperature
        sys_text = ((system or "") + "\n\nOutput strictly valid JSON matching the schema.").strip()
        json_schema = schema.model_json_schema()
        key = self._result_key("structured", role, sys_text, prompt, json_schema, temperature, images)
        hit = self._cache_get(key, f"{role}/{schema.__name__}")
        if hit is not None:
            return hit
        custom_print("AI_INPUT", f"--- PROMPT ({role}) ---\n{prompt}\n----------------")
        text, model, usage = await self._route(
            lambda: self._gemini_structured(role, prompt, json_schema, sys_text, temperature, images),
            lambda: self._claude_structured(role, prompt, json_schema, sys_text, images))
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
        async def gemini():
            resp, model, usage = await self._generate(role, prompt, dict(temperature=temperature, max_output_tokens=max_tokens), system)
            return resp.text or "", model, usage

        out, model, usage = await self._route(gemini, lambda: self._claude(role, prompt, system, max_tokens))
        out = out.strip()
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
