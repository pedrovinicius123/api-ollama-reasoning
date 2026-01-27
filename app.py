"""
API Ollama Reasoning - Aplicação Flask para Raciocínio Matemático com IA

Este módulo principal gerencia a aplicação web que permite aos usuários:
- Criar contas e fazer login
- Submeter perguntas para processamento com raciocínio em profundidade
- Gerar artigos estruturados sobre os tópicos investigados
- Visualizar historicamente os logs de processamento

Dependências principais:
- Flask: Framework web
- Turbo-Flask: Atualizações em tempo real usando WebSockets
- MongoEngine: ORM para MongoDB
- WTForms: Validação de formulários
- Markdown: Conversão de conteúdo para HTML
"""

from flask import Flask, session, render_template, redirect, url_for, request, flash, copy_current_request_context
from turbo_flask import Turbo
from flask_caching import Cache
from functools import wraps
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
import concurrent
import threading

from backend.database.db import db, upload_file, Upload, User
from backend.ollama_thread_manager import read_markdown_to_html, ollama_queue
from dotenv import load_dotenv
import os, uuid

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# ============================================================================
# CONFIGURAÇÕES DO FLASK E EXTENSÕES
# ============================================================================

# Inicializa a aplicação Flask
app = Flask(__name__)

# Definir chave secreta para sessões e tokens CSRF (a partir de .env)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")

# Configuração do MongoDB - URI obtida do arquivo .env
app.config['MONGODB_HOST'] = f"mongodb+srv://almeidaxavier:{os.getenv('MONGODB_PASSWORD')}@ollamaapi.ic5dh8p.mongodb.net/?appName=OllamaAPI"

# Tempo de vida da sessão do usuário (1 hora)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)

# Inicializa o Turbo-Flask para atualizações em tempo real
turbo = Turbo()
cache = Cache(config = {
    "DEBUG": True,          # some Flask specific configs
    "CACHE_TYPE": "SimpleCache",  # Flask-Caching related configs
    "CACHE_DEFAULT_TIMEOUT": 300
})

# ============================================================================
# INICIALIZAÇÃO DAS EXTENSÕES
# ============================================================================

# Ativa o Turbo-Flask na aplicação
turbo.init_app(app)

# Inicializa o MongoEngine para acesso ao banco de dados
db.init_app(app)

# Inicializa o cache
cache.init_app(app)
executor = None

# Inicializa o ThreadManager que gerencia threads de processamento

# ============================================================================
# FUNÇÕES UTILITÁRIAS
# ============================================================================

def check_if_logged_in(f):
    """
    Decorator que verifica se o usuário está autenticado.
    
    Se o usuário não estiver logado (session['logged_in'] não existir ou ser False),
    redireciona para a página de login. Caso contrário, permite o acesso à rota.
    
    Args:
        f: Função de rota a ser protegida
        
    Returns:
        function: Função decorada com verificação de autenticação
        
    Exemplo:
        @app.route("/dashboard")
        @check_if_logged_in
        def dashboard():
            return "Página protegida"
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in") or not session.get("username"):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

@app.before_first_request
def before_first_request():
    global active_threads
    executor = ThreadPoolExecutor()
    threading.Thread(target=update_load, args=(executor, )).start()
    active_threads = []

def update_load(executor:ThreadPoolExecutor):
    def run_executor(task, data, key, is_article):
        running = True
        while running:
            try:
                print(next(data))
                task(next(data), key, is_article)
            except StopIteration:
                break

    def task(data, key, is_article):
        if not is_article:
            turbo.push(turbo.update(render_template("_response_fragment.html", content=data), f"responseContent-{key}"))
        else:
            turbo.push(turbo.update(render_template("_article_fragment.html", article=data), f"articleContent-{key}"))

    while True:              
        for future in concurrent.futures.as_completed(ollama_queue.active_requests):
            
            #print(future.result())
            gen, key, is_article = future.result()
            executor.submit(run_executor, task, gen, key, is_article)
            ollama_queue.active_requests.remove(future)
            

# ============================================================================
# ROTAS DA APLICAÇÃO - AUTENTICAÇÃO
# ============================================================================

@app.route("/", methods=["GET", "POST"])
@check_if_logged_in
def home():
    """
    Página inicial (dashboard) do usuário autenticado, com formulário para submeter uma pergunta/problema para raciocínio profundo.
    
    Este formulário coleta:
    - Pergunta: O problema a ser resolvido
    - Contexto: Informações adicionais para orientar o raciocínio
    - Configurações de raciocínio: max_width, max_depth, n_tokens
    - Modelo: Qual modelo Ollama usar
    - API Key: Autenticação para Ollama
    - Log Dir: Diretório para armazenar logs
    
    GET: Exibe o formulário vazio
    POST: 
        1. Valida o formulário
        2. Cria arquivos iniciais (context.md, response.md, article.md)
        3. Redireciona para /write com os parâmetros para iniciar raciocínio
    
    Returns:
        str: HTML do formulário ou redirecionamento para processar pergunta
        
    Database Operations:
        - Cria 3 arquivos iniciais por pergunta:
          * context.md: Contexto fornecido
          * response.md: Vazio, será preenchido com resposta
          * article.md: Vazio, será preenchido se artigo for gerado
    
    Redirect:
        - Redireciona para rota /write com todos os parâmetros
        - Inicia processamento de raciocínio
    """
    
    if request.method == 'POST':
        # Obtém usuário autenticado
        usr = User.objects(username=session.get('username')).first()
        
        # Define diretório de log (padrão: 'default_log' se não fornecido)
        log_dir_value = request.form.get('log_dir').lower() or 'default_log'
        cits = [log.strip() for log in request.form.get('citations').split('#')]
        while '' in cits:
            cits.remove('')

        session_id = uuid.uuid4()
        # Cria arquivo de contexto inicial
        upload_file(
            user=usr,
            log_dir=log_dir_value,
            filename='context.md',
            raw_file=f"Initial context: {request.form.get('context')}".encode('utf-8'),
            description=request.form.get('description'),
            session_id=session_id,
            citations=cits,
            initial=True
        )

        # Cria arquivo de resposta vazio (será preenchido durante raciocínio)
        upload_file(
            user=usr,
            log_dir=log_dir_value,
            filename='response.md',
            raw_file=" ".encode('utf-8'),
            description=request.form.get('description'),
            session_id=session_id,
            citations=cits,
            initial=True
        )

        # Cria arquivo de artigo vazio (será preenchido se gerado)
        upload_file(
            user=usr,
            log_dir=log_dir_value,
            filename='article.md',
            raw_file=" ".encode('utf-8'),
            session_id=session_id,
            description=request.form.get('description'),
            citations=cits,
            initial=True
        )

        # Redireciona para iniciar o raciocínio com os parâmetros
        return redirect(url_for('write', 
            query=request.form.get('query'), 
            prompt=None, 
            username=session.get('username'), 
            log_dir=log_dir_value, 
            model=request.form.get('model_name'), 
            max_width=request.form.get('max_width'), 
            max_depth=request.form.get('max_depth'), 
            n_tokens=request.form.get('n_tokens') if request.form.get('n_tokens') is not None else 10000, 
            api_key=request.form.get('api_key')
        ))
    
    return render_template('form.html')



@app.route("/login", methods=['GET', 'POST'])
def login():
    """
    Rota de login de usuário.
    
    Permite que usuários se autentiquem usando nome de usuário ou email + senha.
    Valida as credenciais contra o banco de dados MongoDB.
    
    GET: Exibe o formulário de login
    POST: Processa as credenciais e cria uma sessão autenticada
    
    Validações:
    - Verifica se usuário/email existe no banco de dados
    - Valida a senha usando hash bcrypt
    - Inicia uma sessão permanente (1 hora de duração)
    
    Returns:
        str: HTML do formulário de login ou redirecionamento para home
        
    Flash Messages:
        - "No users matching the description" (erro): Usuário não encontrado
        - "Sucessfully logged in": Login bem-sucedido
        - "Incorrect Password" (erro): Senha incorreta
    """
    
    if request.method == 'POST':
        username_or_email = request.form.get('username_or_email')
        password = request.form.get('password')

        # Define a sessão como permanente (com expiração)
        session.permanent = True
        
        # Busca por usuário usando username OU email
        users = User.objects(__raw__={'$or':[{'username':username_or_email},{'email':username_or_email}]})
        

        if users.first() is None:
            flash('No users matching the description', 'error')
        else:
            usr = users.first()
            
            # Valida a senha contra o hash armazenado
            if usr.check_password(password):
                flash('Sucessfully logged in')
                session['logged_in'] = True
                session['username'] = usr.username

                # Garante que as mudanças na sessão sejam persistidas
                session.modified = True
                return redirect("/")
            else:
                flash('Incorrect Password', 'error')

    return render_template('user_forms.html', login=True, ch_user=False)


@app.route("/register", methods=["GET", "POST"])
def register():
    """
    Rota de registro de novo usuário.
    
    Permite que novos usuários criem uma conta com:
    - Nome de usuário único
    - Email válido e único
    - Senha com confirmação
    
    Validações:
    - Nome de usuário não pode estar duplicado
    - Email não pode estar duplicado
    - Emails são validados pelo WTForms
    - Senhas devem corresponder
    
    GET: Exibe formulário de registro
    POST: Cria novo usuário e inicia sessão autenticada
    
    Returns:
        str: HTML do formulário de registro ou redirecionamento para home
        
    Flash Messages:
        - "Username or email already registered" (erro): Duplicação de dados
    
    Database:
        - Cria novo documento User no MongoDB
        - Hash de senha gerado automaticamente
    """
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        phone = request.form.get('phone')

        session.permanent = True
        
        # Verifica se username ou email já estão registrados
        existing = User.objects(__raw__={'$or':[{'username':username},{'email':email}]})
        
        if existing.first() is not None:
            flash('Username or email already registered', 'error')
        else:
            
            session['logged_in'] = True
            session['username'] = username
            
            # Cria novo usuário com ID sequencial
            usr = User(username=username, email=email, phone=phone)
            usr = User(username=username, email=email, phone=phone)
            
            # Gera hash bcrypt da senha
            usr.generate_password_hash(password)
            
            # Persiste no banco de dados
            usr.save()

            # Garante que as mudanças na sessão sejam persistidas
            session.modified = True

            return redirect(url_for('home'))
        
    return render_template('user_forms.html', login=False, ch_user=False)

# ============================================================================
# ROTAS DE VISUALIZAÇÃO DE LOGS
# ============================================================================

@app.route("/search", methods=['GET', 'POST'])
def view_logs_links():
    if request.method == 'POST':
        search_query = request.form.get('search', '').strip()
        return redirect(url_for('view_logs_links_query', query=search_query.lower(), all=request.args.get('all', False)))

    projects = []
    if request.args.get('all', False):
        projects = Upload.objects(filename__contains='/response.md')
        return render_template('search.html', researches=projects, username=False)

    else:
        user = User.objects(username=session.get('username', '')).first()
        projects = Upload.objects(filename__contains='/response.md', creator=user)

        return render_template('search.html', researches=projects, username=session.get('username', ''))

@app.route("/search", methods=["GET", "POST"])
def view_logs_links_query():
    if request.method == "POST":
        search_query = request.form.get('search', '').strip()
        return redirect(url_for('view_logs_links_query', search=search_query.lower(), all=request.args.get('all', False)))
    
    projects = []
    query = request.args.get('query', '')
    if request.args.get('all', False):
        projects = Upload.objects(filename__contains=query+'/response.md')
        return render_template('search.html', researches=projects, username=False)

    else:
        if query == '':
            return redirect(url_for('view_logs_links', all=True))

        username = session.get('username')
        user = User.objects(username=username).first()
        projects = Upload.objects(filename__contains=query+'/response.md', creator=user)

        for project in projects:
            project.save()

        return render_template('search.html', researches=projects, username=username)

@app.route("/<username>/<log_dir>")
def view_logs(username: str, log_dir: str):
    """
    Exibe um log específico (run) completo de um usuário.
    
    Mostra:
    - Resposta ao problema (response.md)
    - Artigo gerado (article.md) - se disponível
    - Contexto original (context.md) - armazenado para referência
    
    Args:
        username (str): Nome do proprietário do log
        log_dir (str): Nome do diretório do log
    
    Returns:
        str: HTML com conteúdo do log renderizado ou redirecionamento em erro
        
    Flash Messages:
        - "User not found" (erro): Usuário não existe
        - "No logs found for this user/log_dir" (erro): Log não encontrado
        
    Variables de Template:
        - response: Objeto Upload do response.md
        - article: Objeto Upload do article.md (pode ser None)
        - read_markdown_to_html: Função para renderizar Markdown
    """
    user = User.objects(username=username).first()
    
    if user is None:
        flash("User not found", 'error')
        return redirect(url_for('home'))

    # Busca o arquivo de resposta para este log
    response = Upload.objects(filename__contains=f"{log_dir}/response.md", creator=user).first()

    # Busca o arquivo de artigo (pode não existir)
    article = Upload.objects(filename__contains=f"{log_dir}/article.md", creator=user).first()
    
    if response is None:
        flash('No logs found for this user/log_dir', 'error')
        return redirect(url_for('home'))
    
    return render_template('response.html', response=response.file.read().decode("utf-8"), article=article.file.read().decode("utf-8"), response_id=response.session_id, article_id=article.session_id, read_markdown_to_html=read_markdown_to_html)


# ============================================================================
# ROTAS DE PROCESSAMENTO - RACIOCÍNIO E GERAÇÃO DE ARTIGOS
# ============================================================================

@app.route("/<username>/<log_dir>/write_logs")
@check_if_logged_in
@cache.cached(timeout=1000)
def write(username: str, log_dir: str):
    """
    Inicia o processamento de raciocínio em profundidade para uma pergunta.
    
    Esta rota:
    1. Valida que o usuário autenticado é o proprietário do log
    2. Extrai os parâmetros de raciocínio da query string
    3. Cria uma nova thread para executar o raciocínio
    4. Adiciona a thread ao ThreadManager para ser iniciada
    5. Retorna a página de resposta para receber atualizações em tempo real
    
    Parâmetros de Query String:
        - query (str): Pergunta/problema a ser resolvido
        - model (str): Nome do modelo Ollama a usar
        - max_width (int): Número de alternativas por nível (2-10)
        - max_depth (int): Profundidade máxima de raciocínio (2-20)
        - n_tokens (int): Número máximo de tokens a gerar
        - api_key (str): Chave de API para autenticação Ollama
        - prompt (str): Prompt customizado do sistema
    
    Args:
        username (str): Proprietário do log (deve ser o usuário autenticado)
        log_dir (str): Diretório para armazenar logs do processamento
    
    Returns:
        str: HTML da página de resposta com WebSocket conectado para updates
        
    Segurança:
        - Verifica que username == session['username']
        - Redireciona para home se não autorizado
    
    Processing:
        - Cria thread gerenciada pelo ThreadManager
        - Não bloqueia a requisição principal
        - Atualizações enviadas via Turbo-Flask WebSocket
    """
    # Verifica autorização: usuário só pode processar seus próprios logs
    if username != session.get("username"):
        return redirect(url_for("home"))

    user = User.objects(username=username).first()
    params = {
        "log_dir":log_dir.lower(),
        "username": username,
        "user": user,
    
        **request.args
    }
    
    ollama_queue.submit_request_response(app, **params)
    response = Upload.objects(filename__contains=os.path.join(log_dir, 'response.md'), creator=user).first()
    
    # Retorna página para receber atualizações em tempo real
    return render_template('response.html', response=False, article=False, response_id=response.session_id, read_markdown_to_html=read_markdown_to_html)


@app.route("/<username>/<log_dir>/write_article", methods=["GET", "POST"])
@check_if_logged_in
@cache.cached(timeout=1000)
def write_article(username: str, log_dir: str):
    """
    Inicia a geração de um artigo estruturado baseado no log de raciocínio.
    
    Esta rota:
    1. Valida autorização do usuário
    2. Extrai parâmetros de configuração (modelo, iterações, API key)
    3. Cria thread para gerar o artigo
    4. Adiciona ao ThreadManager para execução
    5. Retorna página com WebSocket conectado para atualizações em tempo real
    
    Parâmetros de Query String:
        - model (str): Nome do modelo Ollama a usar
        - iterations (int): Número de iterações (páginas) do artigo
        - api_key (str): Chave de API Ollama
    
    Args:
        username (str): Proprietário do log (deve ser o usuário autenticado)
        log_dir (str): Diretório contendo o response.md base
    
    Returns:
        str: HTML da página com conteúdo sendo gerado em tempo real
        
    Processing:
        - Busca o response.md existente para contexto
        - Cria e enfileira thread no ThreadManager
        - Inicializa article.md vazio ou existente
    
    Threading:
        - Não bloqueia requisição principal
        - Atualizações via WebSocket Turbo-Flask
    """
    # Extrai parâmetros de configuração

    user = User.objects(username=username).first()
    params = {
        "user":user,
        "username": username,
        "log_dir": log_dir,
        **request.args

    }
    
    ollama_queue.submit_request_article(app, **params)
    
    # Busca o response.md associado para contexto
    response = Upload.objects(filename__contains=os.path.join(log_dir, "response.md"), creator=user).first()
    article = Upload.objects(filename__contains=os.path.join(log_dir, "article.md"), creator=user).first()
    return render_template('response.html', response=response.file.read().decode("utf-8"), article=False, article_id=article.session_id, read_markdown_to_html=read_markdown_to_html)


# ============================================================================
# ROTAS DE SUBMISSÃO DE FORMULÁRIOS E REMOÇÃO DE DADOS PELO USUÁRIO
# ============================================================================

@app.route("/<username>/<log_dir>/delete")
@check_if_logged_in
def delete(username:str, log_dir:str):
    if session.get("username") != username:
        flash("You cannot delete others logs", "error")
        return redirect(url_for("home"))

    usr = User.objects(username=username).first()
    objs = Upload.objects(filename__contains=log_dir, creator=usr)
    ollama_queue.cleanup_session(*map(lambda x:x.session_id, objs))
    
    for obj in objs:
        obj.delete()

    return redirect(url_for("home"))

@app.route('/logout')
@check_if_logged_in
def logout():
    session['username'] = None
    return redirect('/login')

@app.route('/delete')
@check_if_logged_in
def delete_account():
    user = User.objects(username=session.get('username')).first()
    creations = Upload.objects(creator=user)
    if user:
        user.delete()
        for c in creations:
            c.delete()

    session['username'] = None
    return redirect('/login')

@app.route('/update', methods=['GET', 'POST'])
def update_user():
    if request.method == 'POST':
        old_username = request.form.get('old_username')
        if old_username == session.get('username'):
            new_username = request.form.get('new_username')
            user = User.objects(username=session.get('username')).first()

            session['username'] = new_username
            user.username = new_username
            user.save()

            return redirect('/')
    return render_template("user_forms.html", login=False, ch_user=True)


@app.route("/submit_article", methods=["GET", "POST"])
@check_if_logged_in
def submit_article():
    """
    Formulário para gerar um artigo baseado em um log de raciocínio existente.
    
    Permite que o usuário solicite a geração de um artigo estruturado
    sobre um problema que foi previamente resolvido.
    
    GET: Exibe formulário com opções de configuração
    POST:
        1. Valida os dados do formulário
        2. Redireciona para /write_article com parâmetros
        3. Inicia geração do artigo em background
    
    Parâmetros do Formulário:
        - log_dir (str): Qual log usar como base
        - n_iterations (int): Quantas iterações/páginas para o artigo
        - api_key (str): Chave de autenticação Ollama
        - model (str): Qual modelo usar (opcional, usa padrão se vazio)
    
    Returns:
        str: HTML do formulário ou redirecionamento para processar artigo
        
    Estrutura do Artigo Gerado:
        - Introdução (20% das iterações)
        - Declaração do Problema (20% das iterações)
        - Metodologia (20% das iterações)
        - Resultados (20% das iterações)
        - Conclusão (20% das iterações)
    
    Model Selection:
        - Se modelo não for especificado, usa thinker.model (padrão)
    """
    
    if request.method == 'POST':

        # Redireciona para iniciar geração do artigo
        
        return redirect(url_for("write_article", 
            username=session.get("username"), 
            **request.form
        ))
    
    user = User.objects(username=session.get("username")).first()
    objs = Upload.objects(creator=user)
    if not objs:
       return render_template("create_article.html", logs=[])
    objs = [obj for obj in objs if obj.filename.split("/")[1] == "response.md"]
    return render_template("create_article.html", logs=objs)


# ============================================================================
# INICIALIZAÇÃO DA APLICAÇÃO
# ============================================================================

if __name__ == '__main__':
    """
    Ponto de entrada da aplicação.
    
    Inicia o servidor Flask com:
    - debug=True: Modo de depuração (auto-reload em mudanças)
    - threaded=True: Suporta múltiplas threads para requisições concorrentes
    
    AVISO: Para produção, use um servidor WSGI como Gunicorn
    Exemplo: gunicorn -w 4 -b 0.0.0.0:5000 app:app
    
    A aplicação roda em http://localhost:5000 por padrão
    """
    # Habilita threading para que threads de worker possam fazer requisições
    # HTTP de volta para este servidor
    app.run(debug=True, threaded=True)
