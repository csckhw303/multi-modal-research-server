from langchain_cohere import CohereRerank
from src.config.index import appConfig

cohereReranker = CohereRerank(
    cohere_api_key=appConfig["cohere_api_key"], model="rerank-english-v3.0"
)
