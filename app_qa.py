import time
from rag import RagService
import streamlit as st
import config_data as config

#标题
st.title("智能客服")
st.divider()  # 分隔线

if "message" not in st.session_state:
    st.session_state["message"]= [{"role":"assistant","content":"你好，我是智能客服，有什么问题可以咨询我吗？"}]

if "rag" not in st.session_state:
    st.session_state["rag"] = RagService()
for message  in st.session_state["message"]:
    st.chat_message(message["role"]).write(message["content"])
#在页面最下方提供用户输入栏
prompt=st.chat_input()
if prompt:
    #在页面输出用户提问
    st.chat_message("user").write(prompt)
    st.session_state["message"].append({"role":"user","content":prompt})
    ai_res_list = []
    with st.spinner("AI思考中...."):
        result = st.session_state["rag"].chain.stream({"input":prompt},config=config.session_config)
        #yield

        #new*
        def capture(generator,cache_list):
            for chunk in generator:
                cache_list.append(chunk)
                yield chunk

        st.chat_message("assistant").write_stream(capture(result,ai_res_list))
        st.session_state["message"].append({"role":"assistant","content":"".join(ai_res_list)})
