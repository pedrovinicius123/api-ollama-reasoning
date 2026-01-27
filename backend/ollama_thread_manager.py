# backend/ollama_service.py
import threading
from markupsafe import Markup
from markdown import markdown
from concurrent.futures import ThreadPoolExecutor
from backend.api.model.reasoning import Reasoning
from backend.database.db import User, Upload
import logging
import os
import re


def read_markdown_to_html(content: str):
    """
    Converte conteúdo Markdown com LaTeX para HTML seguro.
    
    Esta função:
    1. Substitui delimitadores LaTeX \\( e \\) por $ (modo inline)
    2. Substitui delimitadores LaTeX \\[ e \\] por $$ (modo bloco)
    3. Converte o Markdown resultante para HTML
    4. Marca o resultado como seguro (Markup) para renderização no Jinja2
    
    Args:
        content (str): Conteúdo em Markdown contendo possíveis expressões LaTeX
        
    Returns:
        Markup: HTML seguro para renderização em templates Jinja2
    """
    # Substitui os delimitadores LaTeX pelos delimitadores markdown-katex
    s = re.sub(r"\\\(|\\\)", "$", content)
    s = re.sub(r"\\\[|\\\]", "$$", s)
    
    # Converte Markdown para HTML
    html_code = markdown(s)
    
    # Retorna como Markup para que o Jinja2 não escape caracteres especiais
    return Markup(html_code)



def store_article(thinker, app, username: str, log_dir: str, iterations:int = 1, n_tokens: int = 65000):
    """
    Gera e armazena um artigo estruturado em uma thread separada.
    
    Esta função executa o gerador de artigos do Reasoning e atualiza a interface
    do usuário em tempo real através do Turbo-Flask conforme o conteúdo é gerado.
    
    O artigo é estruturado com:
    - Introdução (primeiras iterações)
    - Declaração do Problema
    - Metodologia
    - Resultados
    - Conclusão
    
    Args:
        username (str): Nome do usuário proprietário do artigo
        log_dir (str): Diretório de logs para armazenar o artigo
        model (str, optional): Nome do modelo Ollama a usar. Defaults to None.
        iterations (str, optional): Número de iterações para gerar o artigo. Defaults to "1".
        api_key (str, optional): Chave de API para autenticação Ollama. Defaults to None.
        n_tokens (int, optional): Número máximo de tokens a gerar. Defaults to 65000.
        
    Returns:
        None: Atualiza o banco de dados e envia updates para o frontend via WebSocket
        
    Nota:
        - Executa dentro de um contexto de aplicação Flask
        - Usa Turbo para atualizar a interface em tempo real
        - Armazena o resultado no banco MongoDB
    """
    iterations_int = 0

    # Valida e converte o número de iterações
    try:
        iterations_int = int(iterations)
    except Exception:
        iterations_int = 1

    # Configura os parâmetros do gerador de raciocínio

    article_content = ""
    usr = User.objects(username=username).first()
    article_obj = Upload.objects(filename__contains=log_dir, creator=usr).first()
    
    
    # Executa o gerador dentro de um contexto de aplicação Flask
    # (necessário para acesso ao banco de dados e sessões)
    with app.app_context():
        gen, _ = thinker.write_article(username=username, log_dir=log_dir, iterations=iterations_int, n_tokens=n_tokens, searched_in=article_obj.citations)

        logging.info(f'gen {gen}')
        for chunk in gen:
            if chunk:
                article_content += chunk
                # Atualiza a interface com o novo fragmento de conteúdo
                yield read_markdown_to_html(article_content)

def store_response(thinker, app, query: str, username: str, log_dir: str):
    """
    Processa uma pergunta através do sistema de raciocínio em profundidade e armazena a resposta.
    
    Esta função:
    1. Valida e configura os parâmetros do sistema de raciocínio
    2. Executa o raciocínio em profundidade com múltiplas alternativas
    3. Atualiza a interface em tempo real através do Turbo-Flask
    4. Armazena a resposta no banco de dados MongoDB
    
    Parâmetros do raciocínio:
    - max_width: Número de alternativas a explorar em cada nível
    - max_depth: Profundidade máxima de exploração
    - n_tokens: Número máximo de tokens gerados
    
    Args:
        query (str): Pergunta/problema a ser resolvido
        username (str): Nome do usuário que submeteu a pergunta
        log_dir (str): Diretório para armazenar logs do processamento
        model (str, optional): Modelo Ollama a usar. Defaults to None.
        max_width (str, optional): Número de alternativas por nível. Defaults to None.
        max_depth (str, optional): Profundidade máxima de raciocínio. Defaults to None.
        n_tokens (str, optional): Número máximo de tokens. Defaults to None.
        api_key (str, optional): Chave de API Ollama. Defaults to None.
        prompt (str, optional): Prompt customizado do sistema. Defaults to None.
        
    Returns:
        None: Atualiza banco de dados e frontend em tempo real
        
    Nota:
        - A função para quando recebe "Solved the problem" do modelo
        - Mantém contexto de raciocínio anterior para continuidade
    """

    response_content = ""
    usr = User.objects(username=username).first()
    
    resp_obj = Upload.objects(filename__contains=log_dir, creator=usr).first()


    # Executa o raciocínio dentro de um contexto de aplicação Flask
    with app.app_context():
        gen, response = thinker.reasoning_step(username=username, log_dir_main=log_dir, log_dirs=resp_obj.citations, query=query or "")
        for chunk in gen:
            # Para quando o problema é resolvido
            if "SOLVED" in chunk:
                break
            
            if chunk:
                response_content += chunk
                # Atualiza a interface com novo conteúdo
                yield read_markdown_to_html(response_content)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class OllamaRequestQueue:
    def __init__(self, max_workers=3):
        self.tasks = []
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.active_requests = []
        self.request_lock = threading.RLock()
        self.thread_local = threading.local()

        logger.info(f"OllamaService inicializado com {max_workers} workers")
        
    def submit_request_article(self, app, **kwargs):
        sess_id = Upload.objects(filename__contains=os.path.join(kwargs.get("log_dir"), "article.md"), creator=kwargs.get("user")).first().session_id
        future = self.executor.submit(self._process_request_article, app, **kwargs, session_id=sess_id)
        with self.request_lock:
            self.active_requests.append(future)

        logger.info(f"Requisição de artigo submetida! modelo: {kwargs.get("model")}")
        return sess_id

    def submit_request_response(self, app, **kwargs):
        sess_id = Upload.objects(filename__contains=os.path.join(kwargs.get("log_dir"), "article.md"), creator=kwargs.get("user")).first().session_id
        future = self.executor.submit(self._process_request_response, app, **kwargs, session_id=sess_id)
        with self.request_lock:
            self.active_requests.append(future)

        logger.info(f"Requisição de Raciocínio realizada com sucesso! modelo: {kwargs.get("model")}")
        return sess_id

    def _get_reasoning_instance(self, model="deepseek-v3.1:671b-cloud", **kwargs):
        if not hasattr(self.thread_local, "reasoning_instance"):
            self.thread_local.reasoning_instance = {}
        
        key = f"{model}-{kwargs.get("username")}/{kwargs.get("request_prompt")}-{kwargs.get("api_key")}"
        logging.info(f"Key: {key}")
        if key not in self.thread_local.reasoning_instance:
            logging.info("Key not found, add new one.")
            self.thread_local.reasoning_instance[key] = Reasoning(
                api_key=kwargs.get("api_key"),
                max_depth=kwargs.get("max_depth"),
                max_width=kwargs.get("max_width"),
                model_name=model,
                n_tokens_default=kwargs.get("n_tokens")
            )

        return self.thread_local.reasoning_instance[key]

        
    def _process_request_article(self, app, **kwargs):
        logging.info(f"Session key: {kwargs.get("session_id")}")
        thinker = self._get_reasoning_instance(**kwargs)
        print("N Tokens", kwargs.get("n_tokens"))
        result = store_article(
            thinker,
            app,
            username=kwargs.get("username"),
            n_tokens=kwargs.get("n_tokens"),
            iterations=kwargs.get("iterations"),
            log_dir=kwargs.get("log_dir"),
        
        )

        return result, Upload.objects(filename__contains=kwargs.get("log_dir"), creator=kwargs.get("user")).first().session_id, True


    def _process_request_response(self, app, **kwargs):
        thinker = self._get_reasoning_instance(**kwargs)
        result =  store_response(
            thinker,
            app,
            query=kwargs.get("query"),
            username=kwargs.get("username"),
            log_dir=kwargs.get("log_dir"),

        )

        return result, Upload.objects(filename__contains=kwargs.get("log_dir"), creator=kwargs.get("user")).first().session_id, False

    def join_session(self, *session_ids):
        with self.request_lock:
            for session_id in session_ids:
                if session_id in self.active_requests and self.active_requests[session_id].done():
                   del self.active_requests[session_id]
                   return True
            return False

    def cleanup_session(self, *session_ids):
        with self.request_lock:
            for session_id in session_ids:
                if not len(self.active_requests) == 0 and session_id in self.active_requests:
                    del self.active_requests[session_id]

# Singleton global
ollama_queue = OllamaRequestQueue()
