"""Hardcoded chat modes: a persona, its tool policy and its reasoning default.

Pure data — deliberately no config import, so `prompt.py` can use this without
pulling in the settings bootstrap. `routes/modes.py` serves the same registry to
the UI, so the titles and hints live here only.
"""

from dataclasses import dataclass
from typing import Literal

ToolsPolicy = Literal["auto", "on", "off"]
ThinkLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class Mode:
    id: str
    title: str
    hint: str
    icon: str
    #: Appended to the base system prompt, after the soft rules.
    block: str = ""
    tools: ToolsPolicy = "auto"
    #: Applied to the pane when the user switches into this mode. None means
    #: "no opinion" — the reasoning level the user already chose is left alone.
    think: ThinkLevel | None = None
    #: Soft base rules this block countermands, by key of `SOFT_RULES`.
    overrides: tuple[str, ...] = ()
    #: Extra slash-command tokens, besides the id itself.
    aliases: tuple[str, ...] = ()
    #: Confirmation text shown before switching into this mode. `{max_iter}` is
    #: filled in per request, so it always matches the live tool budget.
    warn: str = ""


# Soft rules are keyed so a mode can drop the one it contradicts instead of
# arguing with it in its own block — the model never sees a rule it is told to
# break. The tools rule varies with the policy: a mode with no tools must not be
# handed a paragraph instructing it to search.
SOFT_RULES: dict[str, str] = {
    "language": "Reply in the language the user writes in.",
    "tools": (
        "You have tools available. Use web_search for facts you are unsure about or that may be recent, "
        "and fetch_page to read a specific URL from search results. Use calc for any non-trivial arithmetic "
        "and python for computations or short scripts. Keep tool use purposeful — one search is usually enough."
    ),
    "tools_forced": (
        "You must use your tools before making any factual claim. Use web_search to find sources and fetch_page "
        "to read one in full when a snippet is not enough. Do not answer a factual question from memory alone, "
        "and do not state anything you could not check — say plainly which claims you could not verify."
    ),
}


MODES: dict[str, Mode] = {
    m.id: m
    for m in (
        Mode(
            id="assistant",
            title="Assistant",
            hint="General help, tools available",
            icon="🤖",
            block="",
        ),
        Mode(
            id="text-only",
            title="Text-only",
            hint="Answers from its own knowledge, no lookups",
            icon="💬",
            block=(
                "Answer from your own knowledge alone. Do not mention tools and do not offer to look anything "
                "up. If a question needs current or verifiable information you do not have, say so plainly."
            ),
            tools="off",
            think="low",
            aliases=("text",),
        ),
        Mode(
            id="teacher",
            title="Teacher",
            hint="Explains step by step and checks you followed",
            icon="🎓",
            block=(
                "Teach rather than simply answer. Build the explanation step by step, define each new term as it "
                "appears, and close with a one-line recap of the key idea. When the topic allows it, finish by "
                "asking one short question that checks whether the explanation landed."
            ),
            think="medium",
        ),
        Mode(
            id="plain-language",
            title="Plain language",
            hint="Same thing, said simply",
            icon="🗣️",
            block=(
                "Write for a reader with no background in the subject: short sentences, everyday words, and a "
                "concrete comparison whenever an idea is abstract. When a technical term is unavoidable, define "
                "it in the same sentence you use it."
            ),
            think="low",
            aliases=("plain", "simple"),
        ),
        Mode(
            id="examiner",
            title="Examiner",
            hint="Quizzes you one question at a time",
            icon="📝",
            block=(
                "You are examining the user on a topic, not lecturing on it. Ask exactly one question at a time "
                "and wait for their answer. After each answer give a short verdict — what was right, what was "
                "wrong or missing — then ask the next question. Never reveal an answer before they have tried it."
            ),
            think="high",
        ),
        Mode(
            id="solver",
            title="Solver",
            hint="Works the problem through and verifies it",
            icon="🧮",
            block=(
                "Solve the problem completely. State every assumption you have to make, show the reasoning, and "
                "verify the result wherever a check is possible. Mark the final answer clearly and keep it "
                "separate from the working."
            ),
            think="high",
        ),
        Mode(
            id="fact-check",
            title="Fact-check",
            hint="Verifies claims against sources, verdict each",
            icon="🔎",
            block=(
                "Break the user's text into its individual factual claims. Check each one with web_search, "
                "opening a source with fetch_page when the snippet is not enough to judge. Give a verdict per "
                "claim — supported, contradicted, or unverifiable — and cite the evidence behind it. Keep "
                "verified fact separate from your own inference, and say plainly when sources disagree or when "
                "you could not check a claim."
            ),
            tools="on",
            think="high",
            aliases=("fact", "check"),
            warn=(
                "Fact-check verifies every claim with web searches. A long, claim-heavy message can use all "
                "{max_iter} tool iterations, and the answer may be cut off when the budget runs out. Continue?"
            ),
        ),
        Mode(
            id="research",
            title="Research",
            hint="Several sources, synthesised with links",
            icon="📚",
            block=(
                "Research the question across several focused searches rather than one broad one, and read the "
                "most promising pages with fetch_page. Then write a structured answer that separates what the "
                "sources agree on, where they conflict, and where the evidence is thin. Link the sources you "
                "relied on."
            ),
            tools="on",
            think="high",
        ),
        Mode(
            id="devils-advocate",
            title="Devil's advocate",
            hint="Argues the strongest case against you",
            icon="😈",
            block=(
                "Argue the strongest case against the user's position. Steelman it first, so they can see you "
                "understood it, then attack the load-bearing assumptions rather than the wording. Be rigorous and "
                "specific rather than contrarian for its own sake, and concede the points where their position "
                "actually holds."
            ),
            think="medium",
            aliases=("devil", "advocate"),
        ),
        Mode(
            id="editor",
            title="Editor",
            hint="Fixes the text, preserves your voice",
            icon="🖊️",
            block=(
                "Return the edited text first, then a short list of the changes that alter meaning — leave pure "
                "style fixes out of the list. Preserve the author's voice and register, and add nothing they did "
                "not ask for. When a sentence is ambiguous, ask which reading they meant instead of guessing."
            ),
            tools="off",
            think="low",
        ),
        Mode(
            id="translator",
            title="Translator",
            hint="Translates only, keeps tone and terms",
            icon="🌐",
            block=(
                "Translate the user's text. Preserve tone, register, names, numbers and formatting, and render "
                "idioms as the nearest equivalent in the target language rather than word for word. Use the "
                "target language the user names, and English when they name none. Output only the translation "
                "unless the user asks for notes; where a term has no good equivalent, translate it and add a "
                "short note about that term alone."
            ),
            tools="off",
            think="low",
            overrides=("language",),
            aliases=("translate",),
        ),
        Mode(
            id="condense",
            title="Condense",
            hint="Shrinks the text without losing facts",
            icon="✂️",
            block=(
                "Compress the text to its essential meaning at roughly the length the user asks for, keeping "
                "every load-bearing fact, figure and caveat. Cut repetition and hedging, never substance, and "
                "invent nothing that was not in the original. Prefer plain prose over nested lists unless the "
                "original is itself a list."
            ),
            tools="off",
            think="low",
            aliases=("summary", "summarize", "tldr"),
        ),
        Mode(
            id="brainstorm",
            title="Brainstorm",
            hint="Many options, no pruning",
            icon="💡",
            block=(
                "Generate many distinct options, each with a one-line rationale. Favour quantity and range over "
                "polish at this stage, and include a couple of ideas that are unusual but defensible. Do not "
                "prune or rank unless the user asks; when they do, follow with a shortlist and say what you "
                "dropped."
            ),
            think="high",
        ),
        Mode(
            id="planner",
            title="Planner",
            hint="Turns a goal into ordered steps and risks",
            icon="🗓️",
            block=(
                "Turn the goal into an ordered plan of concrete steps. State the assumptions the plan rests on, "
                "what has to happen before what, the risks that would derail it, a rough sizing for each step, "
                "and the decisions the user has to make before starting."
            ),
            think="high",
        ),
        Mode(
            id="programmer",
            title="Programmer",
            hint="Working code, edge cases covered",
            icon="👨‍💻",
            block=(
                "Answer with complete, runnable code and state the language and version it targets. Keep prose to "
                "the minimum needed to explain a non-obvious choice, and handle the edge cases the code will meet. "
                "Say how to run or test it, and point out anything you deliberately left out."
            ),
            think="high",
            aliases=("code",),
        ),
        Mode(
            id="critic",
            title="Critic",
            hint="Leads with the worst problems and how to fix them",
            icon="🧐",
            block=(
                "Review the material and lead with its most important weaknesses. Be specific about each one and "
                "point at the part you mean, separate flaws that break the whole thing from nits, and give a "
                "concrete fix per problem. Do not rewrite the material yourself unless the user asks."
            ),
            think="high",
        ),
    )
}

DEFAULT_MODE_ID = "assistant"


def get_mode(mode_id: str | None) -> Mode:
    """Resolve an id, falling back to the default for None or anything unknown.

    Never raises: a session row can outlive a rename or a removal in this table.
    """
    if mode_id and mode_id in MODES:
        return MODES[mode_id]
    return MODES[DEFAULT_MODE_ID]


def soft_rules(mode: Mode | None) -> list[str]:
    """The base rules that survive this mode, in order.

    `None` is the plain assistant: every rule applies.
    """
    tools: ToolsPolicy = mode.tools if mode is not None else "auto"
    overrides = mode.overrides if mode is not None else ()
    out: list[str] = []
    if "language" not in overrides:
        out.append(SOFT_RULES["language"])
    if tools == "on":
        out.append(SOFT_RULES["tools_forced"])
    elif tools == "auto" and "tools" not in overrides:
        out.append(SOFT_RULES["tools"])
    return out


def public_modes(max_iter: int) -> list[dict]:
    """The registry as the UI consumes it. The warning is formatted per request
    so it always quotes the live budget rather than an import-time snapshot."""
    return [
        {
            "id": m.id,
            "title": m.title,
            "hint": m.hint,
            "icon": m.icon,
            "tools": m.tools,
            "think": m.think,
            "aliases": list(m.aliases),
            "warn": m.warn.format(max_iter=max_iter) if m.warn else "",
        }
        for m in MODES.values()
    ]
