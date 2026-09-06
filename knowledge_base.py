"""
知识库
"""
import datetime
import os
import config_data as config
import hashlib
from langchain_chroma import Chroma
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

def check_md5(md5_str:str):
    """检查传入的md5字符串是否被处理过"""
    if not os.path.exists(config.md5_path):
        #如果文件不存在
        open(config.md5_path, 'w',encoding="utf-8").close()
        return False
    else:
        with open(config.md5_path, 'r', encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line == md5_str:
                    return True     #如果文件中存在该md5字符串，则返回True
        return False    #如果文件中不存在该md5字符串，则返回False

def save_md5(md5_str:str):
    """将传入的md5字符串，记录到文件内保存"""
    with open(config.md5_path,'a',encoding="utf-8") as f:
        f.write(md5_str+"\n")

def get_string_md5(input_str:str,encoding='utf-8'):
    """将传入的字符串，转换为md5字符串"""

    #将字符串转换为bytes字节数组
    str_bytes=input_str.encode(encoding=encoding)

    #创建md5对象
    md5_obj = hashlib.md5()     #创建md5对象
    md5_obj.update(str_bytes)    #更新md5对象，传入bytes字节数组
    md5_hex = md5_obj.hexdigest() #获取md5字符串
    return md5_hex

class KnowledgeBaseService(object):

    def __init__(self):
        #如果文件不存在则创建，存在则跳过
        os.makedirs(config.persist_directory, exist_ok=True)
        self.chroma = Chroma(
            collection_name=config.collection_name,
            embedding_function=DashScopeEmbeddings(model=config.embedding_model_name),
            persist_directory=config.persist_directory,
        )   #向量存储的实例Chroma向量数据库
        self.spliter = RecursiveCharacterTextSplitter(
            chunk_size=config.chunk_size,           #每个文本段最大长度
            chunk_overlap=config.chunk_overlap,    #每个文本段之间的重叠长度
            separators=config.separators,  # 分隔符列表
            length_function=len,  # 用于计算文本长度的函数
        )   #文本分割器的对象

    def upload_by_str(self,data,filename):
        """将传入的字符串进行向量化，存入向量数据库"""
        #先得到传入字符串的md5值
        md5_hex = get_string_md5(data,encoding='utf-8')

        if check_md5(md5_hex):
            return "[跳过]，内容已存在知识库中"

        if len(data) > config.max_spliter_char_number:
            knowledge_chucks:list[str] = self.spliter.split_text(data)
        else:
            knowledge_chucks = [data]

        metadata = {
            "source":filename,
            "create_time":datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "operation":"呵",
        }
        self.chroma.add_texts(
            knowledge_chucks,
            metadatas = [metadata for _ in knowledge_chucks],
        )
        save_md5(md5_hex)

        return "[成功]内容已经成功载入向量库"

    def upload_text(self, data: str, filename: str):
        """兼容旧上传页面的调用名称。"""
        return self.upload_by_str(data, filename)


if __name__ == '__main__':
    service=KnowledgeBaseService()
    r=service.upload_by_str("周杰伦","testfile")
    print(r)
