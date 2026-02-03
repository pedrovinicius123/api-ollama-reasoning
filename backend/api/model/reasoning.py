"""
Sistema de Raciocínio em Profundidade com Geração de Artigos

Este módulo implementa um sistema de raciocínio matemático estruturado que:
1. Quebra problemas em múltiplas alternativas (width)
2. Explora alternativas em profundidade (depth)
3. Mantém contexto e histórico de raciocínio
4. Gera artigos estruturados sobre as descobertas

Características:
- Raciocínio iterativo: Múltiplas passagens para aprofundamento
- Alternativas paralelas: Explora múltiplos caminhos simultaneamente
- Contexto acumulativo: Cada passo tem acesso ao histórico
- Geração de artigos: Estrutura automática com seções específicas
- Validação: Apenas conceitos e teoremas bem conhecidos
- Renderização: Math em KaTeX para display

Dependências:
- ollama: Interface com servidor Ollama
- mongoengine: Persistência em MongoDB
- math: Cálculos de alocação de iterações
"""

from backend.api.model.api_main import make_request_ollama_reasoning
from backend.database.db import Upload, User, upload_file
import os
import math


# ============================================================================
# GERADORES DE PROMPTS - TEMPLATES PARAMETRIZADOS
# ============================================================================

generate_prompt = lambda width, prompt: f"""
THINK LOUDLY!
1. Break the problem into {width} step alternatives to adress it
2. Choose one alternative
3. DO NOT USE CONJECTURES. Only use well known theorems, lemmas and mathematical concepts. 

PROBLEM: {prompt}

Do not write an answer yet, only propose the alternatives.
Use $$ for block math and $ for inline math.
Answer with the language of the Problem (for example, if the statement is written in pt-br, answer with that language)
"""
"""
Prompt inicial para gerar alternativas de solução.

Instrui o modelo a:
1. Quebrar problema em {width} alternativas
2. Selecionar uma para explorar
3. Usar apenas conceitos matemáticos conhecidos
4. Não propor conjecturas (apenas conceitos estabelecidos)
5. Renderizar math em KaTeX
6. Responder as questões em sua própria linguagem

Retorna: string com o prompt formatado
"""


continue_prompt = lambda width: f"""
Now, extensively create an mathematical approximation using the anterior alternative,
AND PROPOSE {width} NEW ONES, BASED ON THE PREVIOUS ALTERNATIVE, TO CONTINUE THE TASK.

Remember: don't use any conjecture, only theorems, lemmas and other mathematical concepts well known.
IF SOLUTION:
    return SOLVED
ELSE:
    return PROGRESS

*Display math in $$ for block equations and $ for inline*
"""
"""
Prompt para continuação do raciocínio em profundidade.

Instrui o modelo a:
1. Explorar a alternativa selecionada com rigor matemático
2. Propor {width} novas alternativas baseadas no resultado
3. Retornar 'SOLVED' se solução for encontrada
4. Retornar 'PROGRESS' se continuação for necessária
5. Usar apenas conceitos bem conhecidos

Retorna: string com o prompt formatado
"""


article_prompt = lambda iterations: f"""
Now, write a detailed article about the problem developed in this chain of thoughs
Write at the language present on the chain of thoughs!
Use the following structures

1. Introduction: Briefly introduce the problem in the chain of thoughs and its significance.
2. Problem Statement: Clearly state it and any assumptions.
3. Methodology: Describe the approach taken to solve the problem in the chain of thoughs, including any algorithms, math theorems, or techniques used.
4. Results: Present the findings, including any equation displayed on the logs.
5. Conclusion: Summarize the findings and discuss any implications or future work.

Render math in KATEX form.
MAKE SURE TO WRITE WITHIN THE NUMBER OF ITERATIONS BELLOW
AND DO NOT WRITE EVERYTHING AT ONCE!
Iterations {iterations}

If iteration between 1 - {math.floor(iterations*0.2)}, write or develop introduction (ONLY!!!) (1.)
If iteration between {math.floor(iterations*0.2)} - {math.floor(iterations*0.4)}, write or develop the problem statement (ONLY!!!) (2.)
If iteration between {math.floor(iterations*0.4)} - {math.floor(iterations*0.6)}, write or develop the methodology (ONLY!!!) (3.)
If iteration between {math.floor(iterations*0.6)} - {math.floor(iterations*0.8)}, write or develop results (ONLY!!!) (4.)
If iteration between {math.floor(iterations*0.8)} - {iterations}, write or develop conclusion (ONLY!!!) (5.)

Current_iteration: 1
"""
"""
Prompt inicial para geração de artigo estruturado.

Estrutura do artigo (com alocação automática de iterações):
- Introdução: 20% das iterações
- Declaração do Problema: 20% das iterações
- Metodologia: 20% das iterações
- Resultados: 20% das iterações
- Conclusão: 20% das iterações

Usa divisão inteira para garantir cobertura completa.

Retorna: string com o prompt formatado
"""


article_prompt_continue = lambda iteration, iterations: f"""
Continue writing the article, expanding it.
Make sure to include any additional insights or observations that may be relevant.
Render math in KATEX form.

If iteration between 1 - {math.floor(iterations*0.2)}, write or develop introduction (ONLY!!!) (1.)
If iteration between {math.floor(iterations*0.2)} - {math.floor(iterations*0.4)}, write or develop the problem statement (ONLY!!!) (2.)
If iteration between {math.floor(iterations*0.4)} - {math.floor(iterations*0.6)}, write or develop the methodology (ONLY!!!) (3.)
If iteration between {math.floor(iterations*0.6)} - {math.floor(iterations*0.8)}, write or develop results (ONLY!!!) (4.)
If iteration between {math.floor(iterations*0.8)} - {iterations}, write or develop conclusion (ONLY!!!) (5.)

DO NOT USE GENERATED DATA, JUST WRITE AT AN ANALITICAL WAY
ADD SUBSECTIONS AS NEEDED
ALSO KEEP IN MIND TO NOT WRITE THIS PROMPT AND NOT REPEAT THE ANTERIOR SECTIONS!!
Current_iteration: {iteration}

"""
"""
Prompt para continuação de artigo.

Mantém informações de alocação de iterações para consistência.
Foca em expandir Metodologia e Resultados nas iterações centrais.

Retorna: string com o prompt formatado
"""


# ============================================================================
# CLASSE PRINCIPAL - REASONING
# ============================================================================

class Reasoning:
    """
    Sistema de Raciocínio em Profundidade para Problemas Matemáticos.
    
    Implementa um algoritmo de raciocínio estruturado que:
    1. Gera múltiplas alternativas para resolver um problema
    2. Explora cada alternativa em profundidade
    3. Acumula contexto entre passos para continuidade
    4. Detecta quando um problema foi resolvido
    5. Gera artigos sobre o processo e resultado
    
    Parâmetros de Raciocínio:
    - max_width: Número de alternativas a explorar por nível (padrão: 5)
    - max_depth: Profundidade máxima de exploração (padrão: 20)
    - model: Modelo Ollama a usar (padrão: "deepseek-v3.1:671b-cloud")
    - n_tokens_default: Tokens máximos por geração (padrão: 100000)
    
    Attributes:
        max_width (int): Número de alternativas por nível de raciocínio
        max_depth (int): Profundidade máxima de exploração
        model (str): Nome do modelo Ollama
        n_tokens_default (int): Número padrão de tokens a gerar
        api_key (str): Chave de autenticação para Ollama
    
    Methods:
        reasoning_step: Executa um passo de raciocínio
        write_article: Gera artigo estruturado baseado no raciocínio
    """
    
    def __init__(self, api_key: str, max_width: int, max_depth: int, model_name: str = "deepseek-v3.1:671b-cloud", n_tokens_default: int = 100000):
        """
        Inicializa o sistema de raciocínio.
        
        Args:
            api_key (str): Chave de autenticação para Ollama (pode ser atualizada depois)
            max_width (int): Número de alternativas a explorar por nível
            max_depth (int): Profundidade máxima de raciocínio em passos
            model_name (str): Nome do modelo Ollama. Defaults to "deepseek-v3.1:671b-cloud"
            n_tokens_default (int): Tokens máximos por geração. Defaults to 100000
        
        Exemplos:
            >>> # Criar sistema com parâmetros padrão
            >>> thinker = Reasoning('', max_width=5, max_depth=20)
            >>> 
            >>> # Depois atualizar a chave de API
            >>> thinker.api_key = 'chave_real_aqui'
        """
        self.max_width = max_width
        self.max_depth = max_depth
        self.model = model_name
        self.n_tokens_default = n_tokens_default
        self.api_key = api_key

    def reasoning_step(self, username: str, log_dir_main:str, log_dirs: list, query: str):
        """
        Executa um processo de raciocínio em profundidade sobre um problema.
        
        Este método:
        1. Busca o arquivo de contexto (context.md) para histórico
        2. Busca o arquivo de resposta (response.md) para acumular resultado
        3. Executa loop de raciocínio até max_depth iterações
        4. Em cada iteração:
           - Gera prompt inicial ou de continuação
           - Faz requisição ao Ollama
           - Acumula resposta no contexto
           - Verifica se problema foi "SOLVED"
           - Atualiza os arquivos no banco de dados
        5. Retorna generator que streaming da resposta
        
        Estrutura de Contexto Acumulativo:
        ```
        Contexto inicial:
        1. System prompt (instruções)
        2. Histórico de perguntas e respostas anteriores
        
        A cada iteração:
        - Adiciona novo prompt
        - Adiciona resposta do modelo
        - Próxima iteração vê tudo anterior
        ```
        
        Args:
            username (str): Nome do usuário proprietário do log
            log_dir (str): Diretório para armazenar os logs
            query (str): Pergunta/problema principal a resolver
            init (bool): Se True, é o início (usa generate_prompt). 
                        Se False, usa continue_prompt. Defaults to False
            prompt (str, optional): Prompt customizado (não é usado atualmente)
        
        Yields:
            str: Chunks de conteúdo da resposta conforme são gerados
            
        Returns:
            Tuple[Generator, int]: (gerador de chunks, código de status HTTP)
        
        Raises:
            ValueError: Se context.md ou response.md não forem encontrados
        
        Database Persistence:
            - Busca context.md: histórico de raciocínio
            - Busca response.md: respostas acumuladas
            - Atualiza após cada iteração:
              * context.md: com novo prompt + resposta
              * response.md: com nova resposta
        
        Condição de Parada:
            - Atinge max_depth iterações, OU
            - Resposta contém "SOLVED"
        
        Exemplos:
            >>> gen, status = thinker.reasoning_step(
            ...     username='usuario1',
            ...     log_dir='problema_1',
            ...     query='Qual é a integral de sin(x)?',
            ...     init=True
            ... )
            >>> for chunk in gen:
            ...     print(chunk, end='', flush=True)
        """
        
        # Busca arquivo de contexto (histórico de raciocínio)
        obj_file = Upload.objects(filename__contains=os.path.join(log_dir_main, 'context.md'), creator=User.objects(username=username).first()).first()
        if not obj_file:
            raise ValueError("No context file found for reasoning step.")
        

        # Busca arquivo de resposta (acumula resultado)
        obj_response = Upload.objects(filename__contains=os.path.join(log_dir_main, 'response.md'), creator=User.objects(username=username).first()).first()
        if not obj_response:
            raise ValueError("No response file found for reasoning step.")

        def iterate():
            """
            Função interna que implementa o loop de raciocínio.
            
            Yields:
                str: Chunks da resposta conforme gerados pelo Ollama
                
            Lógica:
            1. Inicia context e response vazios (serão carregados do DB)
            2. Para cada profundidade até max_depth:
               - Seleciona prompt (inicial ou continuação)
               - Faz requisição ao Ollama com context+prompt
               - Stream os chunks enquanto acumula em context
               - Se vê "SOLVED", termina loop
               - Atualiza DB com novo context e response
            3. Retorna após max_depth iterações ou quando SOLVED
            """

            files = [Upload.objects(filename=log_dir).read().decode("utf-8") if Upload.objects(filename=log_dir) else "" for log_dir in log_dirs]
            search_context=" "
            for content in files:
                search_context += content + "\n\n"
                
            context = " "
            response = " "
            break_all = False
            
            # Loop de raciocínio profundo
            for i in range(int(self.max_depth)):
                # Seleciona qual prompt usar
                if i == 0:
                    # Primeiro passo: gerar alternativas iniciais
                    current_prompt = generate_prompt(self.max_width, query)
                else:
                    # Passos seguintes: continuar explorando
                    current_prompt = continue_prompt(self.max_width)
                # Faz requisição ao Ollama
                r = make_request_ollama_reasoning(
                    api_key=self.api_key, 
                    model_name=self.model, 
                    prompt=current_prompt, 
                    context=search_context+context, 
                    n_tokens=self.n_tokens_default
                )
                
                # Acumula o prompt no contexto para próxima iteração
                context += "\n\n" + current_prompt + "\n\n"

                # Stream dos chunks da resposta
                for chunk in r:
                    if 'message' in chunk:
                        content = chunk['message'].get('content', '')
                        # Acumula em contexto e resposta
                        context += content
                        response += content

                        # Verifica se problema foi resolvido
                        if "SOLVED" in content:
                            yield "SOLVED"
                            break_all=True
                            break

                        # Yield para o frontend em tempo real
                        yield content

                if break_all:
                    break

                # Atualiza response.md no banco de dados
                upload_file(
                    user=User.objects(username=username).first(),
                    log_dir=log_dir_main,
                    filename='response.md',
                    raw_file=(response+"\n").encode('utf-8')
                )

                # Atualiza context.md no banco de dados (para continuidade)
                upload_file(
                    user=User.objects(username=username).first(),
                    log_dir=log_dir_main,
                    filename='context.md',
                    raw_file=(context+"\n").encode('utf-8')
                )

        return iterate(), 200

    def write_article(self, username: str, log_dir: str, searched_in:list, iterations: int, n_tokens: int):
        
        """
        Gera um artigo estruturado baseado no raciocínio realizado.
        
        Este método:
        1. Carrega o contexto/response do raciocínio anterior
        2. Executa múltiplas iterações para construir artigo
        3. Em cada iteração:
           - Usa prompt estruturado para seção específica
           - Acumula conteúdo anterior para contexto
           - Faz requisição ao Ollama
           - Atualiza article.md no banco
        
        Estrutura do Artigo (com alocação automática):
        ```
        Iterações 1-20%: Introdução
        Iterações 20%-40%: Declaração do Problema
        Iterações 40%-60%: Metodologia
        Iterações 60%-80%: Resultados
        Iterações 80%-100%: Conclusão
        ```
        
        Esta estrutura é mantida no prompt para orientar geração.
        
        Args:
            username (str): Proprietário do artigo
            log_dir (str): Diretório contendo o raciocínio anterior
            iterations (int): Número de iterações (seções) a gerar
            n_tokens (int): Tokens máximos por iteração
        
        Yields:
            str: Chunks do artigo conforme gerados
            
        Database:
            - Lê context e response do raciocínio anterior
            - Atualiza article.md após cada iteração
            - Acumula conteúdo para contexto das próximas iterações
        
        Exemplos:
            >>> gen = thinker.write_article(
            ...     username='usuario1',
            ...     log_dir='problema_1',
            ...     iterations=5,
            ...     n_tokens=65000
            ... )
            >>> for chunk in gen:
            ...     print(chunk, end='', flush=True)
        """

        usr = User.objects(username=username).first()
        def iterate(usr=usr):
            """
            Função interna que itera para gerar artigo.
            
            Yields:
                str: Chunks do artigo sendo gerado
                
            Lógica:
            1. Acumula conteúdo anterior (prev_generated)
            2. Para cada iteração até iterations:
               - Seleciona prompt (inicial ou continuação)
               - Faz requisição ao Ollama
               - Stream chunks
               - Acumula em prev_generated
               - Atualiza article.md no DB
            """
            prev_generated = " "
            logs = " "
            for i in range(int(iterations)):
                # Seleciona prompt apropriado para iteração
                if i == 0:
                    logs = Upload.objects(filename__contains=os.path.join(log_dir, "response.md"), creator=usr).first()
                    prompt = article_prompt(iterations)
                else:
                    prompt = article_prompt_continue(i+1, iterations)
                
                # Acumula prompt anterior para contexto
                gen = "\n\n"
                
                # Faz requisição ao Ollama
                r = make_request_ollama_reasoning(
                    api_key=self.api_key, 
                    model_name=self.model, 
                    prompt=prompt, 
                    context=logs.file.read().decode('utf-8')+"\n\n"+prev_generated, 
                    n_tokens=n_tokens
                )
                
                # Stream dos chunks
                for chunk in r:
                    if 'message' in chunk:
                        content = chunk['message'].get('content', '')
                        # Acumula em prev_generated
                        prev_generated += content
                        gen += content

                    # Yield para frontend em tempo real
                    yield content

                # Atualiza article.md após cada iteração
                upload_file(
                    user=User.objects(username=username).first(),
                    log_dir=log_dir,
                    filename='article.md',
                    raw_file=prev_generated.encode('utf-8')
                )

            yield [f'[{s}](s)' for s in searched_in].join('\n')

        return iterate(), 200
