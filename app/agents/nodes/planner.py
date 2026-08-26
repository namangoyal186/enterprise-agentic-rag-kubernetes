import logfire

from app.agents.state import AgentState
from app.gateway import get_langchain_llm

# Portkey-backed LLM: fallback + cache + retry — same .invoke() interface as ChatOpenAI
llm = get_langchain_llm(feature="planner")


def planner_node(state: AgentState):
    """
    The Planner determines if a search is needed based on the ENTIRE conversation.
    """
    # Get the conversation history (excluding the latest message)
    history = ""
    for msg in state["messages"][:-1]:
        role = "User" if msg["role"] == "user" else "Assistant"
        history += f"{role}: {msg['content']}\n"

    user_message = state["messages"][-1]["content"] if state["messages"] else ""

    prompt = f"""
    You are an intelligent Assistant Planner for an Enterprise Kubernetes & Cloud Infrastructure system.
    Analyze the conversation history and the latest user message.

    CONVERSATION HISTORY:
    {history}

    LATEST MESSAGE:
    "{user_message}"

    Rules:
    1. Return 'CONVERSATIONAL' ONLY if the message is purely a casual greeting ("hi", "hello", "hey"), social pleasantry ("thank you", "bye", "cool"), or asking who you are.
    2. If the message contains ANY technical term (e.g. "kubectl", "pod", "deployment", "intel", "service", "ingress", "network", "helm", "cpu", "memory", "manifest", "file", "document"), or asks any infrastructure question, you MUST generate a refined 2-6 word search query for the Qdrant vector database.

    Output ONLY 'CONVERSATIONAL' or the refined search query.
    """



    with logfire.span("🧠 Planner Decision"):
        decision = llm.invoke(prompt).content.strip()
        logfire.info(f"Intent identified: {decision}")

    if decision == "CONVERSATIONAL":
        return {
            "current_query": "CONVERSATIONAL",
            "status": "Handling conversationally (using memory)...",
            "plan": ["Intent: Conversational/Memory", "Retrieval: Skipped"],
        }

    return {
        "current_query": decision,
        "status": f"Technical research needed. Searching for: {decision}",
        "plan": ["Intent: Technical", f"Search Term: {decision}"],
    }
