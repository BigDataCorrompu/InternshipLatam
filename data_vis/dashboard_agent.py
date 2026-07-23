from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage


class DashboardAgent:
    BASE_INSTRUCTIONS = """You are the assistant embedded in a job offer dashboard, \
        helping users explore and analyze job listings.

        You always reply in English, concisely, as if speaking directly to the person \
        using the dashboard.

        You have access to tools that let you:
        - Apply filters to the offers currently shown on the dashboard (location, \
        score, seniority, remote, keywords, etc.)
        - Extract specific data from the CURRENTLY FILTERED offers (top offers, top \
        companies, or the full detail of one specific offer)
        - Search the web for information not available in the local dataset (e.g. \
        market salaries, company news, industry trends)

        Important behavior rules:
        - You never see the raw dataset directly — always use a tool to get real data. \
        Never invent numbers, company names, or offer details.
        - If the user asks about the "current" or "filtered" offers, use the data \
        extraction tool — do not assume nothing has been filtered.
        - If a question needs live/external information (salaries, company reputation, \
        market trends), use the web search tool rather than guessing.
        - Tools return raw, technical summaries (lists, stats, key-value style text). \
        Never paste a tool's output verbatim to the user — always rewrite it into a \
        clear, natural, conversational answer, as if you were explaining the result \
        yourself. Keep it short and precise: lead with the direct answer, add only \
        the details the user actually needs.
        - If a tool returns "no offers match" or similar, say so plainly instead of \
        making up a result.
        """

    def __init__(self, llm, tools: list, system_context: str = "", max_iterations: int = 4, session_id: str = "default"):
        # prompt_cache_key must stay stable across calls in the same session
        # for Mistral to actually reuse the cached prefix (system prompt + history).
        llm_with_cache = llm.bind(prompt_cache_key=f"dashboard-{session_id}")
        self._tools = {t.name: t for t in tools}
        self._llm_with_tools = llm_with_cache.bind_tools(tools)
        self._system_context = system_context
        self._max_iterations = max_iterations

    def __call__(self, question: str, history: list | None = None) -> tuple[str, list]:
        """`history` is the list of prior conversational messages (no system prompt),
        persisted by the caller across turns. Returns (answer, updated_history)."""
        history = history or []

        full_system_prompt = self.BASE_INSTRUCTIONS
        if self._system_context:
            full_system_prompt += "\n" + self._system_context

        messages = [SystemMessage(content=full_system_prompt)] + history + [HumanMessage(content=question)]

        for _ in range(self._max_iterations):
            response = self._llm_with_tools.invoke(messages)
            messages.append(response)
            if not response.tool_calls:
                new_history = messages[1:]  # drop the system message before persisting
                return response.content, new_history
            for call in response.tool_calls:
                tool_fn = self._tools.get(call["name"])
                result = tool_fn.invoke(call["args"]) if tool_fn else f"Unknown tool: {call['name']}"
                messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

        return "I couldn't complete this request within the allowed number of steps.", history