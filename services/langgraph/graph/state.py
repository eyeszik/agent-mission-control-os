from typing import Annotated, Any, Dict, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from .models import AgentRun


class GraphState(TypedDict):
    run: AgentRun
    current_node: str
    # LangGraph requires reducer metadata to be an actual binary callable. The
    # prebuilt add_messages reducer appends new messages and handles message IDs.
    messages: Annotated[list[BaseMessage], add_messages]
    extracted_data: Dict[str, Any]
    validation_status: str
