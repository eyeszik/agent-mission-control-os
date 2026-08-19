import os
import json


def generate_structured(prompt: str, fallback: dict) -> dict:
    """
    Calls the configured LLM for a JSON-structured agency task, falling back to a
    deterministic mock when no OPENAI_API_KEY is configured or the call/parse fails.
    Mirrors the fallback pattern already used in graph/nodes/planner.py.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return fallback

    try:
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.4)
        response = llm.invoke(
            prompt + "\n\nRespond with ONLY a valid JSON object. No markdown fences, no commentary."
        )
        content = response.content.strip()
        if content.startswith("```"):
            content = content.strip("`")
            if "\n" in content:
                content = content.split("\n", 1)[1]
        return json.loads(content)
    except Exception as e:
        print(f"Agency LLM error: {e}")
        return fallback
