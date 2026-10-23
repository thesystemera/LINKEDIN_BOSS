import sys, json, asyncio, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pydantic import BaseModel
from src.config import settings
TMP = Path(tempfile.gettempdir()) / "lb_ai_cache"; TMP.mkdir(exist_ok=True)
settings.DB_PATH = str(TMP / "ai_cache.db")
Path(settings.DB_PATH).unlink(missing_ok=True)
import migrate_db
from src.services.database import Database
Database(settings.DB_PATH); migrate_db.apply_v2(settings.DB_PATH)
from src.services.ai_service import AIService


class Ping(BaseModel):
    reply: str


class Resp:
    def __init__(self, text):
        self.text = text


calls = []
async def fake_generate(self, role, contents, base, system=None):
    calls.append((role, contents, system))
    text = "not json" if "broken" in str(contents) else json.dumps({"reply": f"answer {len(calls)}"})
    return Resp(text), "fake-model", {"prompt": 5000, "cached": 4000, "thinking": 100, "output": 10}
AIService._generate = fake_generate

FAIL = []
def check(name, cond, info=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  ({info})" if info and not cond else ""))
    if not cond: FAIL.append(name)

ai = AIService()
async def main():
    a = await ai.structured("job 1", Ping, role="eval", system="CV")
    b = await ai.structured("job 1", Ping, role="eval", system="CV")
    check("identical request answered from cache", a == b and len(calls) == 1, f"{a} {b} calls={len(calls)}")
    await ai.structured("job 2", Ping, role="eval", system="CV")
    check("different job is a new call", len(calls) == 2)
    await ai.structured("job 1", Ping, role="eval", system="CV v2")
    check("changed candidate data is a new call", len(calls) == 3)
    await ai.structured("job 1", Ping, role="forms", system="CV")
    check("different model role is a new call", len(calls) == 4)
    r = await ai.structured("broken", Ping, role="eval", system="CV")
    await ai.structured("broken", Ping, role="eval", system="CV")
    check("unparseable answers are not cached", r is None and len(calls) == 6, f"calls={len(calls)}")
    settings.AI_CACHE_EPOCH = "2"
    await ai.structured("job 1", Ping, role="eval", system="CV")
    check("bumping AI_CACHE_EPOCH skips old answers", len(calls) == 7)
    settings.AI_CACHE_EPOCH = "1"
    settings.AI_RESULT_CACHE = False
    await ai.structured("job 1", Ping, role="eval", system="CV")
    check("AI_RESULT_CACHE=False always calls", len(calls) == 8)
    settings.AI_RESULT_CACHE = True
asyncio.run(main())

stats = Database(settings.DB_PATH).ai_cache_stats()
check("stats count reuse and tokens saved", stats["hits"] == 1 and stats["input_tokens_saved"] == 5000, str(stats))
check("usage line reports cache hits", "1 answered from cache" in ai.usage_line(), ai.usage_line())
t3, t25, t25p = ai._thinking("gemini-3.8-flash", "eval"), ai._thinking("gemini-2.5-flash", "eval"), ai._thinking("gemini-2.5-pro", "pro")
check("gemini 3 gets a thinking level", t3 is not None and "low" in str(t3.thinking_level).lower(), str(t3))
check("gemini 2.5 gets a thinking budget", t25 is not None and t25.thinking_budget == 1024 and t25p.thinking_budget == 1024, f"{t25} {t25p}")
from src.services.form_engine.answerer import humanize, LONGFORM_RE
h = humanize("It’s a complex pipeline—about 190,000 lines—that fuses depth – and texture… “fast”")
check("humanize: no dashes, curly quotes or ellipsis characters", not any(c in h for c in "—–’“”…"), h)
check("humanize: dashes become plain commas", "pipeline, about 190,000 lines, that fuses" in h, h)
check("'Why <company>?' is a long-form question (pro model)", bool(LONGFORM_RE.search("Why Anthropic?")) and bool(LONGFORM_RE.search("Prompt: Why are you applying to Palantir and why now?")))
print("\nALL PASS" if not FAIL else f"\n{len(FAIL)} FAILED: {FAIL}")
