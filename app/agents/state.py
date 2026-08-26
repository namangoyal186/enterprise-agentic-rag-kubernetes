import operator
from typing import Annotated, List, TypedDict


class AgentState(TypedDict, total=False):
    # Using Annotated with operator.add ensures that messages
    # are appended to the history rather than replaced.
    messages: Annotated[List[dict], operator.add]
    current_query: str
    documents: List[dict] | List[str]
    plan: List[str]

    status: str
    final_answer: str
    user_id: str | None
    thread_id: str | None

