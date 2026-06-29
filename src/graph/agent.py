from langgraph.graph import StateGraph, END

from graph.state import AgentState
from graph.nodes import plan, generate_code, execute_code, finalize, handle_error
from graph.edges import after_execute


def _build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("plan", plan)
    graph.add_node("generate_code", generate_code)
    graph.add_node("execute_code", execute_code)
    graph.add_node("finalize", finalize)
    graph.add_node("handle_error", handle_error)

    graph.set_entry_point("plan")

    graph.add_conditional_edges(
        "plan",
        lambda s: "handle_error" if s.get("error") else "generate_code",
        {"handle_error": "handle_error", "generate_code": "generate_code"},
    )
    graph.add_conditional_edges(
        "generate_code",
        lambda s: "handle_error" if s.get("error") else "execute_code",
        {"handle_error": "handle_error", "execute_code": "execute_code"},
    )
    graph.add_conditional_edges(
        "execute_code",
        after_execute,  # -> "generate_code" | "finalize" | "handle_error"
        {
            "generate_code": "generate_code",
            "finalize": "finalize",
            "handle_error": "handle_error",
        },
    )

    graph.add_edge("finalize", END)
    graph.add_edge("handle_error", END)

    return graph.compile()


agentic_ai = _build_graph()
