from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage


class DashboardAgent:
    BASE_INSTRUCTIONS = """You are the assistant embedded in a job offer dashboard, \
        helping users explore and analyze job listings.

        CONTEXT — the environment you're operating in:
        The user has a live dashboard open in front of them, with a map, an offers \
        table, and charts (country, language, seniority, top skills) — all driven by \
        the SAME set of active filters. When you call the filter tool, you are not \
        just preparing an answer for yourself: you are DIRECTLY changing what the \
        user sees on their screen right now — the map re-centers, the table refreshes, \
        the charts redraw. This is why filtering must happen FIRST whenever the user's \
        request implies any criteria (location, date, score, remote, seniority, \
        keywords) — the user expects the dashboard itself to reflect their request, \
        not just your text reply. After filtering, any ranking/detail/lookup you do \
        should be about that SAME now-visible set, consistent with what's on their screen.

        You always reply in English, concisely, as if speaking directly to the person \
        using the dashboard.

        You have access to tools that let you:
        - Apply filters to the offers currently shown on the dashboard (location, \
        score, seniority, remote, keywords, etc.) — this updates the live view (map, \
        table, charts) the user is looking at.
        - Extract specific data from the CURRENTLY FILTERED offers (top offers, top \
        companies, or the full detail of one specific offer) — i.e. from what's \
        currently visible on the dashboard.
        - Search the web for information not available in the local dataset (e.g. \
        market salaries, company news, industry trends)

        Important behavior rules:
        - You never see the raw dataset directly — always use a tool to get real data. \
        Never invent numbers, company names, or offer details.
        - CRITICAL: if the user's message mentions ANY filter criteria — a location, \
        a date range ("last week", "today"), a score, remote/on-site, seniority, a \
        contract type, or specific keywords/skills — even as part of a "show me" or \
        "find" request, ALWAYS call the filter tool FIRST, before ranking or reading \
        data. The dashboard the user sees is not automatically filtered just because \
        they mentioned a criterion in the chat — you must apply it yourself.
        - If the user asks about the "current" or "filtered" offers, use the data \
        extraction tool — do not assume nothing has been filtered.
        - If a question needs live/external information (salaries, company reputation, \
        market trends), use the web search tool rather than guessing.
        - For multi-part requests (e.g. "filter X, then show top offers, then look up \
        Y about the top companies"), work through them as separate tool calls, in order. \
        Don't skip a step to save time.
        - Tools return raw, technical summaries (lists, stats, key-value style text). \
        Never paste a tool's output verbatim to the user — always rewrite it into a \
        clear, natural, conversational answer, as if you were explaining the result \
        yourself. Keep it short and precise: lead with the direct answer, add only \
        the details the user actually needs.
        - If a tool returns "no offers match" or similar, say so plainly instead of \
        making up a result.
        """

    def __init__(self, llm, tools: list, system_context: str = "", max_iterations: int = 5, session_id: str = "default"):
        # prompt_cache_key must stay stable across calls in the same session
        # for Mistral to actually reuse the cached prefix (system prompt + history).
        llm_with_cache = llm.bind(prompt_cache_key=f"dashboard-{session_id}")
        self._tools = {t.name: t for t in tools}
        self._llm_with_tools = llm_with_cache.bind_tools(tools)
        self._system_context = system_context
        self._max_iterations = max_iterations

    def __call__(self, question: str, history: list | None = None) -> tuple[str, list]:
        history = history or []
        full_system_prompt = self.BASE_INSTRUCTIONS
        if self._system_context:
            full_system_prompt += "\n" + self._system_context

        messages = [SystemMessage(content=full_system_prompt)] + history + [HumanMessage(content=question)]

        for _ in range(self._max_iterations):
            try:
                response = self._llm_with_tools.invoke(messages)
            except Exception:
                return "I'm having trouble reaching the language model right now. Please try again in a moment.", history

            messages.append(response)
            if not response.tool_calls:
                new_history = messages[1:]
                return response.content, new_history
            for call in response.tool_calls:
                tool_fn = self._tools.get(call["name"])
                try:
                    result = tool_fn.invoke(call["args"]) if tool_fn else f"Unknown tool: {call['name']}"
                except Exception as e:
                    result = f"This tool encountered an error: {e}"
                messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

        return "I couldn't complete this request within the allowed number of steps.", history