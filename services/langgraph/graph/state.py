from typing import TypedDict, Annotated, List, Dict, Any
from .models import AgentRun

# The state dictionary that is passed between LangGraph nodes
class GraphState(TypedDict):
    run: AgentRun
    current_node: str
    # Use Annotated with a reducer to append rather than overwrite
    messages: Annotated[List[Dict[str, Any]], "append"]
    extracted_data: Dict[str, Any]
    validation_status: str
