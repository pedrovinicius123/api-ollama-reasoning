# Documentação do Projeto - API Ollama Reasoning

Este documento fornece um resumo da documentação adicionada ao projeto.

## 📋 Visão Geral

O projeto **API Ollama Reasoning** é uma aplicação Flask que implementa um sistema de raciocínio matemático em profundidade usando a API Ollama. Permite que usuários:

- Criem contas e façam login
- Submissem perguntas/problemas para raciocínio profundo
- Vejam o raciocínio em tempo real via WebSocket (Turbo-Flask)
- Gerem artigos estruturados sobre os tópicos investigados
- Visualizem historicamente todos os logs de processamento

## 🏗️ Arquitetura do Projeto

### Estrutura de Diretórios

```
/
├── app.py                          # Aplicação principal Flask
├── thread_manager.py               # Gerenciador de threads
├── requirements.txt                # Dependências Python
├── api/
│   └── model/
│       ├── api_main.py            # Interface Ollama
│       └── reasoning.py           # Sistema de raciocínio
├── database/
│   ├── __init__.py
│   └── db.py                      # Modelos MongoDB
├── templates/                      # Templates HTML
├── static/                         # CSS e assets estáticos
└── DOCUMENTATION.md               # Este arquivo
```

## 📚 Detalhamento dos Arquivos Documentados

### 1. **app.py** - Aplicação Principal Flask

**Responsabilidade**: Gerenciar todas as rotas HTTP e fluxo da aplicação

**Seções Principais**:
- **Configurações**: Inicialização do Flask, Turbo-Flask, MongoEngine
- **Funções Utilitárias**:
  - `read_markdown_to_html()`: Converte Markdown com LaTeX para HTML
  - `check_if_logged_in()`: Decorator de autenticação
- **Funções de Processamento**:
  - `store_article()`: Gera artigos em thread separada
  - `store_response()`: Processa raciocínio em thread separada
- **Rotas de Autenticação**: `/login`, `/register`
- **Rotas de Visualização**: `/`, `/<username>`, `/<username>/<log_dir>`
- **Rotas de Processamento**: `/submit_question`, `/submit_article`, `/write`, `/write_article`

**Fluxo de Execução**:
```
1. Usuário submete pergunta via /submit_question
   ├─> Cria arquivos iniciais (context, response, article)
   └─> Redireciona para /write
2. /write inicia thread para store_response()
   ├─> ThreadManager gerencia a execução
   └─> Turbo-Flask envia updates em tempo real
```

### 2. **thread_manager.py** - Gerenciador de Threads

**Responsabilidade**: Gerenciar fila de threads para processamento assíncrono

**Como Funciona**:
- Executa como thread daemon
- Monitora lista de threads continuamente
- Inicia threads quando adicionadas
- Remove threads completadas
- Usa lock (mutex) para thread-safety

**Thread-Safety**:
```python
# Sempre usar com lock
with manager.lock:
    manager.threads.append(thread)
```

### 3. **api/model/api_main.py** - Interface com Ollama

**Responsabilidade**: Fazer requisições HTTP ao servidor Ollama

**Função Principal**:
- `make_request_ollama_reasoning()`: Requisição streaming ao Ollama

**Parâmetros**:
- `api_key`: Token de autenticação Bearer
- `model_name`: Nome do modelo (ex: "deepseek-v3.1:671b-cloud")
- `prompt`: Mensagem do usuário
- `context`: Histórico de raciocínio
- `n_tokens`: Número máximo de tokens

**Configuração de Geração**:
```python
{
    "temperature": 0.01,    # Muito determinístico
    "num_predict": n_tokens,
    "stream": True          # Streaming habilitado
}
```

### 4. **api/model/reasoning.py** - Sistema de Raciocínio

**Responsabilidade**: Implementar algoritmo de raciocínio em profundidade

**Classe Principal**: `Reasoning`

**Parâmetros**:
- `max_width`: Número de alternativas por nível (padrão: 5)
- `max_depth`: Profundidade máxima de exploração (padrão: 20)
- `model`: Modelo Ollama (padrão: "deepseek-v3.1:671b-cloud")
- `n_tokens_default`: Tokens máximos (padrão: 100000)

**Métodos**:

#### `reasoning_step()`
Executa raciocínio em profundidade sobre um problema.

**Fluxo**:
1. Itera até `max_depth` vezes
2. Gera prompts (inicial ou continuação)
3. Faz requisição ao Ollama
4. Acumula contexto para próxima iteração
5. Para quando vê "SOLVED" ou atinge `max_depth`

**Contexto Acumulativo**:
```
Iteração 1: prompt1 + resposta1
Iteração 2: prompt1 + resposta1 + prompt2 + resposta2
...
Iteração N: histórico completo + promptN + respostaN
```

#### `write_article()`
Gera artigo estruturado em múltiplas iterações.

**Estrutura Automática**:
- Introdução: 20% das iterações
- Declaração do Problema: 20%
- Metodologia: 20%
- Resultados: 20%
- Conclusão: 20%

### 5. **database/db.py** - Modelos MongoDB

**Responsabilidade**: Definir modelos de dados e gerenciar persistência

**Modelos**:

#### `User`
Usuários da aplicação com autenticação.

**Atributos**:
- `id` (int): Identificador único
- `username` (str): Único
- `email` (str): Único, validado
- `password_hash` (str): Hash bcrypt com salt

**Métodos**:
- `generate_password_hash()`: Gera hash bcrypt
- `check_password()`: Valida senha (constant-time comparison)

#### `Upload`
Armazenamento de arquivos (logs) em GridFS.

**Atributos**:
- `creator` (ReferenceField): Referência a User
- `id` (int): Identificador único
- `filename` (str): Caminho do arquivo
- `file` (FileField): Conteúdo em GridFS
- `depth` (int): Metadado de profundidade

**Tipos de Arquivos**:
- `context.md`: Histórico de raciocínio
- `response.md`: Resposta ao problema
- `article.md`: Artigo estruturado (opcional)

#### `upload_file()`
Gerencia uploads com controle de versão.

**Estratégia**:
1. **First-time**: Cria novo Upload vazio
2. **Atualizações**: Acumula conteúdo anterior + novo

**Uso**:
```python
upload_file(
    user=user,
    log_dir='problema_1',
    filename='response.md',
    raw_file=b'conteudo',
    initial=False  # True para uploads iniciais
)
```

### 6. **forms/user.py** - Formulários de Usuário

**Responsabilidade**: Validação de formulários com WTForms

**Formulários**:

#### `SubmitQueryForm`
Submeter pergunta para raciocínio profundo.

**Campos**:
- `query` (str): Pergunta principal
- `context` (str): Contexto orientador
- `api_key` (str): Token Ollama
- `log_dir` (str): Diretório (opcional)
- `max_depth` (int): 2-20
- `max_width` (int): 2-10

#### `CreateArticle`
Gerar artigo baseado em raciocínio.

**Campos**:
- `log_dir` (str): Qual log usar
- `n_iterations` (int): Número de seções
- `api_key` (str): Token Ollama
- `model` (str): Modelo (opcional)

#### `CreateUser`
Registro de novo usuário.

**Campos**:
- `username` (str): Único
- `email` (str): Válido e único
- `password` (str): Confirmação necessária

#### `LoginUser`
Autenticação.

**Campos**:
- `username_or_email` (str): Flexível
- `password` (str): Senha

### 7. **forms/search.py** - Formulário de Busca

**Responsabilidade**: Formulário simples de busca

**Campos**:
- `query` (str): Termo de busca
- Sem validações específicas

## 🔄 Fluxos Principais

### Fluxo de Submissão de Pergunta

```
1. Usuário acessa /submit_question
   ↓
2. Preenche SubmitQueryForm
   - query: "Qual é a integral de sin(x)?"
   - context: "Use matemática rigorosa"
   - max_depth: 10
   - max_width: 5
   - api_key: "token_ollama"
   ↓
3. Submete (POST)
   ↓
4. app.submit_question():
   - Cria 3 arquivos no MongoDB:
     * context.md: Contexto inicial
     * response.md: Vazio
     * article.md: Vazio
   - Redireciona para /write com parâmetros
   ↓
5. /write inicia store_response() em thread
   ↓
6. ThreadManager inicia a thread
   ↓
7. store_response():
   - Configura parâmetros do Reasoning
   - Chama reasoning.reasoning_step()
   - Streams chunks via Turbo-Flask
   - Atualiza context.md e response.md
   ↓
8. Frontend recebe atualizações em tempo real via WebSocket
```

### Fluxo de Geração de Artigo

```
1. Usuário visualiza log em /<username>/<log_dir>
   ↓
2. Clica em "Generate Article"
   ↓
3. Acessa /submit_article
   ↓
4. Preenche CreateArticle:
   - log_dir: "problema_1"
   - n_iterations: 5
   - api_key: "token_ollama"
   ↓
5. Submete (POST)
   ↓
6. app.submit_article():
   - Redireciona para /write_article com parâmetros
   ↓
7. /write_article inicia store_article() em thread
   ↓
8. store_article():
   - Configura parâmetros do Reasoning
   - Chama reasoning.write_article()
   - Executa 5 iterações (estrutura 20% cada seção)
   - Streams chunks via Turbo-Flask
   - Atualiza article.md após cada iteração
   ↓
9. Frontend recebe artigo sendo gerado em tempo real
```

### Fluxo de Autenticação

```
Login:
  1. GET /login → exibe formulário
  2. POST com LoginUser
  3. Busca User por username OU email
  4. Valida senha com check_password()
  5. Cria sessão permanente (1 hora)
  6. Redireciona para /home

Registro:
  1. GET /register → exibe formulário
  2. POST com CreateUser
  3. Valida username e email únicos
  4. Cria User com password_hash
  5. Inicia sessão
  6. Redireciona para /home
```

## 🔐 Segurança

### Autenticação
- Senhas: Hash bcrypt com salt (werkzeug)
- Sessões: Permanentes com expiração (1 hora)
- Decorator: `@check_if_logged_in` para proteção de rotas

### Validação
- Client-side: WTForms valida formato
- Server-side: WTForms valida novamente
- CSRF: Token automático Flask-WTF

### Database
- MongoDB credentials: Via variáveis de ambiente (.env)
- API Keys: Passadas via session, nunca em URL (considerar melhorias)

## 🚀 Como Usar

### Iniciar a Aplicação

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Configurar variáveis de ambiente (.env)
SECRET_KEY=sua_chave_secreta
MONGODB_URI=mongodb://usuario:senha@host/database
# Adicionar outras configurações

# 3. Executar
python app.py
# Acessa em http://localhost:5000
```

### Registrar Novo Usuário

```
1. Clique em "Register"
2. Preencha:
   - Username: seu_usuario
   - Email: seu@email.com
   - Password: senha_segura
3. Confirme a senha
4. Clique "Register"
```

### Submeter Pergunta

```
1. Após login, clique em "Ask Question"
2. Preencha:
   - Query: Sua pergunta
   - Context: Informações relevantes
   - Max Depth: 10 (quantidade de profundidade)
   - Max Width: 5 (alternativas por nível)
   - API Key: Sua chave Ollama
3. Clique "Submit"
4. Veja o raciocínio em tempo real
```

### Gerar Artigo

```
1. Visualize um log completo: /<username>/<log_dir>
2. Clique em "Generate Article"
3. Preencha:
   - Iterations: Número de seções (5-10 recomendado)
   - API Key: Sua chave Ollama
4. Clique "Generate"
5. Veja o artigo sendo escrito em tempo real
```

## 📊 Estrutura de Dados

### Exemplo de Caminho de Arquivo

```
User: "joao_silva"
Log Dir: "problema_1"

Arquivos criados:
1. /workspaces/data/joao_silva/problema_1/context.md
2. /workspaces/data/joao_silva/problema_1/response.md
3. /workspaces/data/joao_silva/problema_1/article.md
```

### Exemplo de Contexto Acumulativo

```
Iteração 1:
context = "
System: THINK LOUDLY!
1. Break problem into 5 alternatives...

Resposta 1: Alternative 1: Use integration by parts...
"

Iteração 2:
context = "
System: THINK LOUDLY!
1. Break problem into 5 alternatives...

Resposta 1: Alternative 1: Use integration by parts...

Continue prompt...
Resposta 2: Now exploring integration by parts...
"
```

## 🔧 Dependências Principais

- **Flask 2.2.5**: Framework web
- **Turbo-Flask 0.8.6**: WebSocket em tempo real
- **MongoEngine 0.29.1**: ORM MongoDB
- **WTForms 3.2.1**: Validação de formulários
- **Flask-WTF 1.2.2**: Integração WTForms+Flask
- **Ollama 0.6.0**: Cliente Python Ollama
- **Markdown 3.9**: Conversão Markdown→HTML

## 📝 Notas Adicionais

### Melhorias Futuras Recomendadas

1. **Segurança**:
   - Usar HTTPS em produção
   - Não passar API keys em URLs (usar variáveis de sessão)
   - Rate limiting para requisições
   - Validação de entrada mais rigorosa

2. **Performance**:
   - Cache de resultados
   - Compressão de respostas
   - Connection pooling com MongoDB
   - Índices de database otimizados

3. **Funcionalidade**:
   - Compartilhamento de logs entre usuários
   - Histórico de buscas
   - Favoritos/Bookmarks
   - Export para PDF/LaTeX

4. **Deployment**:
   - Usar Gunicorn em produção
   - Docker para containerização
   - CI/CD pipeline
   - Monitoramento e logging

## 📞 Contato e Suporte

Para dúvidas ou sugestões sobre a documentação, consulte os arquivos individuais que agora contêm docstrings detalhadas.

---

**Documentação criada em**: 28 de Novembro, 2025
**Versão do Projeto**: 1.0
