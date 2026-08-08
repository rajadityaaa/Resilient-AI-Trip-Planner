"""
Chat Tab UI component.
Implements an interactive conversational assistant with full trip result context.
"""
import json
import streamlit as st
from app.agents.state import TripState
from app.llm.factory import get_llm


def render_chat_tab(trip_result: TripState):
    """
    Render a chat assistant interface with session-persistent chat history.
    Injects the full trip details JSON as system instruction context.
    
    Args:
        trip_result: Completed TripState dict.
    """
    st.subheader("💬 AI Travel Assistant Chat")
    st.write(
        "Ask questions or discuss adjustments for your generated trip "
        "(e.g., 'What can I do instead of Day 2 morning?', 'Are there vegetarian alternatives near Day 3 lunch?')."
    )

    # 1. Initialize chat history in session state
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    # Display chat history
    for message in st.session_state["chat_history"]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # 2. Accept user input
    user_input = st.chat_input("Ask about your trip...")
    if user_input:
        # Display user message in chat container
        with st.chat_message("user"):
            st.markdown(user_input)
        
        # Add user message to chat history
        st.session_state["chat_history"].append({"role": "user", "content": user_input})

        # 3. Generate LLM response with trip result injected as context
        with st.spinner("Assistant is thinking..."):
            try:
                # Prepare system context with trip details
                # Remove large binary elements or repetitive errors to keep prompt clean
                clean_context = dict(trip_result)
                if "errors" in clean_context:
                    # Keep a simplified errors list
                    clean_context["errors"] = [e.get("message", "") for e in clean_context["errors"]]

                context_json = json.dumps(clean_context, indent=2, default=str)
                
                system_instruction = (
                    "You are a premium, expert AI travel consultant. "
                    "The user has planned a trip with the details below. "
                    "Help them customize, refine, or learn more about the destinations, "
                    "restaurants, weather, and schedule. "
                    "Respond conversationally. If they request changes, explain what they can do "
                    "(e.g. 'You could swap the museum on Day 3 for the local food market') but note "
                    "that you are in conversation mode and cannot update the other static tabs directly. "
                    "Only suggest alternative activities from the attractions/restaurants lists already in this trip data. "
                    "If none of those fit what the user is asking, say so honestly rather than suggesting other named places from general knowledge.\n\n"
                    f"CURRENT TRIP STATE:\n{context_json}"
                )

                llm = get_llm()
                response = llm(user_input, system_instruction=system_instruction)
                
                # Display assistant response in chat container
                with st.chat_message("assistant"):
                    st.markdown(response)
                
                # Add assistant response to history
                st.session_state["chat_history"].append({"role": "assistant", "content": response})
            except Exception as e:
                st.error(f"Error calling travel assistant: {e}")
