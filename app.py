import streamlit as st

st.set_page_config(page_title="贪心", page_icon="🧠")
st.title("贪心")

# 缓存 Agent（模型只加载一次）
@st.cache_resource
def get_agent():
    from my_agent import run_agent
    return run_agent

run_agent = get_agent()

# 初始化历史
if "history" not in st.session_state:
    st.session_state.history = []

# 显示历史
for msg in st.session_state.history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])

# 输入
if prompt := st.chat_input("你"):
    # 显示用户消息
    with st.chat_message("user"):
        st.write(prompt)

    # 调用 Agent
    with st.chat_message("assistant"):
        with st.spinner("贪心思考中..."):
            answer, new_history = run_agent(prompt, st.session_state.history)
            st.write(answer)

    # 更新历史
    st.session_state.history = new_history