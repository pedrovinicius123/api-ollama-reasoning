"""
Banco de Dados - Modelos MongoDB com MongoEngine

Este módulo define os modelos de dados persistidos no MongoDB:
- User: Usuários da aplicação com autenticação
- Upload: Armazenamento de arquivos (context, response, article)

Também fornece a função upload_file para gerenciar uploads com
controle de versão e atualizações.

ORM: MongoEngine
Database: MongoDB
Authentication: Werkzeug (bcrypt)
File Storage: GridFS (MongoDB FileField)

Dependências:
- flask_mongoengine: Integração Flask + MongoEngine
- mongoengine: ORM para MongoDB
- werkzeug.security: Hash de senhas
"""

from flask_mongoengine import MongoEngine
from mongoengine import Document, FileField, StringField, IntField, ReferenceField, ListField, ObjectIdField
from werkzeug.security import generate_password_hash, check_password_hash
import os.path as path
import time

# Inicializa a instância do MongoEngine (será configurada pela app Flask)
db = MongoEngine()


# ============================================================================
# MODELO: USER - USUÁRIOS DA APLICAÇÃO
# ============================================================================

class User(Document):
    """
    Modelo de Usuário para autenticação e autorização.
    
    Características:
    - ID numérico único (primary_key)
    - Username único
    - Email único (validado)
    - Password hash (bcrypt com salt)
    - Senhas nunca são armazenadas em texto plano
    
    Collection: users (padrão do MongoEngine)
    
    Attributes:
        id (int): Identificador único (chave primária)
        username (str): Nome de usuário único (ex: 'joao_silva')
        email (str): Email único e válido (ex: 'joao@example.com')
        password_hash (str): Hash bcrypt da senha com salt
    
    Methods:
        generate_password_hash(password): Gera e armazena hash da senha
        check_password(password): Valida senha contra hash armazenado
    
    Validações:
        - username: Obrigatório e único
        - email: Obrigatório e único
        - password_hash: Obrigatório (sempre um hash)
    
    Exemplos:
        >>> # Criar novo usuário
        >>> user = User(id=1, username='joao', email='joao@example.com')
        >>> user.generate_password_hash('senha123')
        >>> user.save()
        >>> 
        >>> # Verificar senha
        >>> user = User.objects(username='joao').first()
        >>> if user.check_password('senha123'):
        ...     print("Login bem-sucedido!")
        
    Notas de Segurança:
        - Senhas são sempre hashadas com bcrypt + salt
        - Hashes são computacionalmente caros para evitar força bruta
        - Nunca armazenar senhas em texto plano
        - Sempre usar check_password() para validar
    """
    
    username = StringField(required=True, unique=True)
    email = StringField(required=True, unique=True)
    phone = StringField(required=True, unique=True)
    password_hash = StringField(required=True)


    def generate_password_hash(self, new_password):
        """
        Gera e armazena o hash bcrypt da senha.
        
        Processa:
        1. Se senha é bytes, converte para string
        2. Usa werkzeug.security.generate_password_hash (bcrypt)
        3. Armazena hash na propriedade password_hash
        
        Args:
            new_password (str | bytes): Senha em texto plano
            
        Returns:
            None: Modifica self.password_hash in-place
        
        Notas:
            - Bcrypt adiciona salt automaticamente
            - Cada chamada gera hash diferente (mesmo texto plano)
            - Recomendado: usar 12+ caracteres na senha
        
        Exemplos:
            >>> user = User(id=1, username='joao', email='joao@example.com')
            >>> user.generate_password_hash('minha_senha_segura_123')
            >>> user.password_hash  # Hash único baseado em salt
        """
        # Converte para string se receber bytes
        if isinstance(new_password, bytes):
            new_password = new_password.decode('utf-8')
        
        # Gera hash usando werkzeug (usa bcrypt internamente)
        self.password_hash = generate_password_hash(new_password)

    def check_password(self, password):
        """
        Valida uma senha contra o hash armazenado.
        
        Processa:
        1. Verifica se password_hash existe
        2. Usa werkzeug.security.check_password_hash
        3. Compara entrada com hash de forma segura
        
        Args:
            password (str): Senha em texto plano a validar
            
        Returns:
            bool: True se senha for válida, False caso contrário
        
        Segurança:
            - Usa constant-time comparison (previne timing attacks)
            - Retorna False se não houver hash armazenado
            - Nunca revela por que falhou (hash inválido ou senha errada)
        
        Exemplos:
            >>> user = User.objects(username='joao').first()
            >>> if user.check_password('minha_senha_segura_123'):
            ...     print("Autenticação bem-sucedida")
            >>> else:
            ...     print("Senha incorreta")
        """
        # Retorna False se não houver hash
        if not getattr(self, 'password_hash', None):
            return False
        
        # Valida usando werkzeug (constant-time comparison)
        return check_password_hash(self.password_hash, password)


# ============================================================================
# MODELO: UPLOAD - ARMAZENAMENTO DE ARQUIVOS
# ============================================================================

class Upload(Document):
    """
    Modelo para armazenamento de arquivos (logs) dos usuários.
    
    Armazena arquivos markdown gerados durante o processamento:
    - context.md: Histórico de raciocínio
    - response.md: Resposta ao problema
    - article.md: Artigo estruturado (se gerado)
    
    Usa GridFS do MongoDB para armazenar arquivos (via FileField).
    
    Collection: uploads (definido em meta)
    
    Attributes:
        creator (ReferenceField): Referência ao User proprietário
        id (int): Identificador único (chave primária)
        depth (int): Profundidade de raciocínio (metadado, padrão: 0)
        citations (list): Citações dos arquivos
        filename (str): Caminho do arquivo (ex: 'log_1/response.md')
        file (FileField): Conteúdo do arquivo em GridFS
    
    Estrutura de Caminho:
        {log_dir}/{filename}
        Ex: 'problema_1/response.md'
        Ex: 'problema_1/article.md'
        Ex: 'problema_1/context.md'
    
    Validações:
        - creator: Obrigatório (ReferenceField para User)
        - filename: Obrigatório
        - file: Obrigatório (FileField do GridFS)
        - citations: Obrigatório (citações do documento)
    
    Exemplos:
        >>> # Criar novo upload
        >>> user = User.objects(username='joao').first()
        >>> upload = Upload(
        ...     id=1,
        ...     creator=user,
        ...     filename='problema_1/response.md'
        ... )
        >>> upload.file.put(b'Conteúdo markdown aqui', content_type='text/markdown')
        >>> upload.save()
        >>> 
        >>> # Buscar uploads de um usuário
        >>> uploads = Upload.objects(creator=user)
        >>> for u in uploads:
        ...     print(u.filename)
        >>> 
        >>> # Ler conteúdo do arquivo
        >>> upload = Upload.objects(filename='problema_1/response.md').first()
        >>> content = upload.file.read()
        >>> print(content.decode('utf-8'))
    
    GridFS:
        - MongoDB automaticamente divide arquivos grandes em chunks
        - Limita-se a 16MB por arquivo (limite MongoDB)
        - Ideal para arquivos até ~50MB
        - Metadados armazenados em collections separadas
    """
    
    creator = ReferenceField(User, required=True)
    depth = IntField(default=0)
    filename = StringField(required=True)
    description = StringField(required=True) 
    file = FileField(required=True)
    session_id = StringField(required=True)
    citations = ListField()

    # Define a collection MongoDB explicitamente
    meta = {'collection': 'uploads'}

    def register_refferences(self, *cits):
        self.citations = list(cits)

# ============================================================================
# FUNÇÃO AUXILIAR: UPLOAD_FILE
# ============================================================================

def upload_file(user: User, log_dir: str, filename: str, raw_file, initial: bool = False, citations:list =[], session_id="", description=''):
    """
    Gerencia upload/atualização de arquivos no banco de dados.
    
    Funcionalidade:
    1. Se arquivo não existe (first-time): cria novo Upload
    2. Se arquivo existe e não é inicial: atualiza com novo conteúdo
    3. Se arquivo existe e é inicial: substitui completamente
    
    Estratégia de Atualização:
    - Uploads iniciais: arquivo vazio
    - Atualizações: acumula conteúdo anterior + novo
    
    Args:
        user (User): Proprietário do arquivo
        log_dir (str): Diretório do log (ex: 'problema_1')
        filename (str): Nome do arquivo (ex: 'response.md')
        raw_file (bytes): Conteúdo do arquivo em bytes
        initial (bool): Se True, cria arquivo vazio. Defaults to False
            - True: para uploads iniciais (cria vazio)
            - False: para atualizações (acumula conteúdo)
        
    Returns:
        Upload: Objeto Upload criado ou atualizado
    
    Database Operations:
        - Query: busca Upload com filename específico do user
        - Create: se não existe (on first upload)
        - Update: se existe e não é initial
        - Replace: file.replace() para atualizar conteúdo GridFS
    
    Exemplos:
        >>> # Primeiro upload (cria vazio)
        >>> user = User.objects(username='joao').first()
        >>> upload_file(
        ...     user=user,
        ...     log_dir='problema_1',
        ...     filename='response.md',
        ...     raw_file=b' ',
        ...     initial=True
        ... )
        >>> 
        >>> # Atualização (acumula conteúdo)
        >>> upload_file(
        ...     user=user,
        ...     log_dir='problema_1',
        ...     filename='response.md',
        ...     raw_file=b'Nova resposta parte 2',
        ...     initial=False
        ... )
        >>> 
        >>> # Resultado: conteúdo acumulado
        >>> upload = Upload.objects(filename='problema_1/response.md').first()
        >>> print(upload.file.read())  # Contém conteúdo anterior + novo
    
    Algoritmo:
        1. Cria caminho completo: log_dir/filename
        2. Tenta buscar Upload existente com esse caminho
        3. Se não encontrado:
           - Lança exceção "File does not exist"
           - Cria novo Upload com ID sequencial
           - Armazena raw_file via GridFS
           - Retorna novo documento
        4. Se encontrado:
           - Se inicial: lê nada (content = b' ')
           - Se não inicial: lê conteúdo anterior
           - Deleta arquivo antigo em GridFS
           - Substitui por conteúdo: anterior + novo
           - Salva atualização
           - Retorna documento atualizado
    
    Erro Esperado:
        Exception("File does not exist") é capturado e tratado
        como sinal para criar novo arquivo
    """
    # Constrói caminho completo do arquivo
    full_path = path.join(log_dir, filename)
    
    
    
    try:
        # Tenta buscar arquivo existente
        
        existing = Upload.objects(filename=full_path, creator=user).first()
        if not existing:
            raise Exception("File does not exists")

    except Exception as err:
        # Arquivo não existe - criar novo
        print(f"File does not exist, creating new upload: {err}")
        
        # Cria novo documento Upload
        new_upload_doc = Upload(creator=user)
        new_upload_doc.filename = full_path
        new_upload_doc.session_id = str(session_id)
        
        # Armazena arquivo via GridFS
        new_upload_doc.file.put(raw_file, content_type="text/markdown")
        new_upload_doc.register_refferences(*citations) if citations else None
        new_upload_doc.description = description
        new_upload_doc.save()

        return new_upload_doc

    else:
        # Arquivo existe - atualizar
        content = b" "
        if not initial:
            # Se não é upload inicial, lê conteúdo anterior
            print("Updating existing file...")
            content = existing.file.read() if existing and existing.file.read() else b" "
            # Remove arquivo antigo do GridFS
            existing.file.delete()

                
        # Replace: substitui conteúdo anterior + novo no GridFS
        existing.file.replace(content + raw_file, content_type="text/markdown")
        existing.register_refferences(*citations)
        existing.save()

        return existing
