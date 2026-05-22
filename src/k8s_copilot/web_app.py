"""K8sCopilot web UI (Streamlit).

Run via:  k8s-copilot-web
(or: streamlit run -m k8s_copilot.web_app)
"""

import streamlit as st

from k8s_copilot.agent import Agent
from k8s_copilot.config import load_config, require_api_key


st.set_page_config(
    page_title="K8sCopilot",
    page_icon="⎈",
    layout="wide",
)


@st.cache_resource
def get_agent() -> Agent:
    """Initialize the agent once per session."""
    cfg = load_config()
    require_api_key(cfg)
    return Agent(cfg)


def render_message(role: str, content: str | dict) -> None:
    """Render a message in the chat history."""
    with st.chat_message(role):
        if isinstance(content, dict):
            if content["type"] == "tool_call":
                st.code(
                    f"→ {content['tool']}({content.get('input', {})})",
                    language="python",
                )
            elif content["type"] == "tool_result":
                with st.expander(f"output: {content['tool']}"):
                    st.code(content["result"][:5000], language="text")
        else:
            st.markdown(content)


def main() -> None:
    st.title("⎈ K8sCopilot")
    st.caption("Natural-language assistant for Kubernetes operations")

    # Sidebar
    with st.sidebar:
        st.header("About")
        st.markdown(
            "Ask questions about your Kubernetes cluster in plain English.\n\n"
            "**Examples:**\n"
            "- show me failing pods in the orders namespace\n"
            "- which deployments are unhealthy?\n"
            "- what's wrong with the orders-api pod?\n"
            "- list nodes and their conditions"
        )
        st.divider()
        st.caption("Read-only. No destructive operations.")
        if st.button("Clear conversation"):
            st.session_state.history = []
            st.session_state.messages = []
            st.rerun()

    # Initialize agent (cached)
    try:
        agent = get_agent()
    except Exception as e:
        st.error(f"Could not initialize agent: {e}")
        st.stop()

    # Display conversation history (for rendering) and Claude message history (for context).
    if "history" not in st.session_state:
        st.session_state.history = []
    if "messages" not in st.session_state:
        st.session_state.messages = []

    for role, content in st.session_state.history:
        render_message(role, content)

    if prompt := st.chat_input("Ask about your cluster..."):
        st.session_state.history.append(("user", prompt))
        render_message("user", prompt)

        events = []

        def on_event(event_type: str, payload: dict) -> None:
            if event_type == "tool_call":
                events.append(("assistant", {"type": "tool_call", **payload}))
            elif event_type == "tool_result":
                events.append(("assistant", {"type": "tool_result", **payload}))

        with st.spinner("Investigating..."):
            try:
                answer, st.session_state.messages = agent.run(
                    prompt,
                    messages=st.session_state.messages,
                    on_event=on_event,
                )
            except Exception as e:
                answer = f"**Error:** {type(e).__name__}: {e}"

        for role, content in events:
            st.session_state.history.append((role, content))
            render_message(role, content)

        st.session_state.history.append(("assistant", answer))
        render_message("assistant", answer)


if __name__ == "__main__":
    main()
