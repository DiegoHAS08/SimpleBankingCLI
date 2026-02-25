Simple Banking CLI

Um sistema bancário via terminal desenvolvido em Python puro, com foco em segurança, integridade de dados e boas práticas de backend.
A proposta foi ir além do CRUD básico e aplicar conceitos reais de engenharia de software que sistemas financeiros utilizam no mundo real.

Objetivo do Projeto

Demonstrar que é possível construir um backend:

Seguro

Transacional

Persistente

Sem dependências externas

Utilizando apenas a biblioteca padrão do Python

Decisões Técnicas (e o porquê)

1. O Problema do Ponto Flutuante
2. 
Nunca utilizei float para valores monetários.

Valores como 10.50 não são representados com precisão binária, o que pode gerar erros acumulativos invisíveis.

Minha solução:

Todo o sistema opera exclusivamente em inteiros (centavos).

R$ 10,50 → 1050

A conversão para formato monetário acontece apenas na camada de exibição.

Resultado: cálculos 100% determinísticos.


2. Segurança de Senhas (Nível Produção) 
Não utilizei MD5, SHA1 ou SHA256 puro.


Minha solução:

PBKDF2-HMAC-SHA256

200.000 iterações

Salt aleatório de 16 bytes por usuário

Comparação segura com secrets.compare_digest

Mesmo em caso de vazamento do arquivo bank.db, as senhas estão protegidas contra:

Ataques de dicionário

Rainbow tables

Timing attacks


3. Atomicidade e ACID
4. 
Transferências bancárias precisam ser atômicas.

Não existe "tirar o dinheiro e torcer para dar certo".


Minha solução:

SQLite em modo WAL (Write-Ahead Logging)

Transações explícitas com BEGIN IMMEDIATE

COMMIT e ROLLBACK controlados manualmente

Se houver falha durante uma operação:

→ O banco retorna ao estado anterior

→ Nenhum saldo fica inconsistente


Modelagem de Dados

O sistema foi modelado para garantir integridade referencial:

Tabelas principais:

users

accounts (relação 1:1 com users)

transactions (registro completo de auditoria)

Relacionamentos são protegidos com foreign keys ativadas no SQLite.


Funcionalidades

Área do Cliente

Login seguro (senha oculta via getpass)

Depósitos

Saques (com validação de saldo)

Transferências entre usuários

Extrato com histórico e timestamps

Área Administrativa

Criação de usuários

Ajuste de saldo (crédito/débito)

Registro de auditoria em todas as operações administrativas

Como Executar

Não é necessário instalar nenhuma biblioteca.

git clone https://github.com/DiegoHAS08/SimpleBankingCLI.git

cd SimpleBankingCLI

python bank_app.py


Na primeira execução o sistema cria automaticamente:
Usuário: admin

Senha:   admin123

⚠ Recomenda-se alterar após o primeiro acesso.

Conceitos Aplicados

Hashing com derivação de chave

Atomicidade (ACID)

Controle transacional manual

Modelagem relacional

Segurança contra SQL Injection (queries parametrizadas)

Tratamento seguro de dinheiro

Separação entre camada de persistência e regra de negócio

Possíveis Evoluções

API REST (FastAPI)

Autenticação via JWT

Interface Web

Testes automatizados (pytest)

Dockerização

Controle de sessão

Sistema de bloqueio por tentativas de login


👨‍💻 Autor
Diego Henrique
Desenvolvedor Web Júnior | PHP • Python • MySQL | APIs REST | Estudante de Análise e Desenvolvimento de Sistemas

Se quiser discutir decisões de arquitetura ou melhorias, estou sempre aberto a feedback.


