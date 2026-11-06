# boorlinkcopy

Copiador de links de lojas + conversor em links de afiliado, com painel web, robô coletor
e segurança em dois fatores.

## Rodar localmente

```bash
cd boorlinkcopy
pip install -r requirements.txt
python -m app          # http://127.0.0.1:8077 (defina PORT/HOST se quiser outro)
```

Variáveis úteis:

| Variável | Para que serve |
|---|---|
| `PORT` / `HOST` | porta e interface do servidor |
| `BOOR_SECRET_KEY` | chave mestra (32+ bytes) que criptografa tokens e segredos 2FA |
| `BOOR_DATA_DIR` | pasta de dados (SQLite + senha offline) |
| `BOOR_OFFLINE_PASSWORD` | define a senha offline de reativação já na primeira execução |
| `BOOR_UNLOCK_TOKEN` | token de emergência (só existe no servidor) para religar após bloqueio |
| `BOOR_DEMO=1` | cria a loja "Loja Demo" com ofertas de exemplo |
| `BOOR_COOKIE_SECURE=1` | cookies só por HTTPS (use em produção) |

A **senha offline** é gerada na primeira execução e salva em `data/senha_offline.txt`.
Guarde-a fora do servidor e apague o arquivo do host.

## O que já está pronto

- **Login** e-mail + senha (PBKDF2), **2FA TOTP** com QR code (Google Authenticator, Authy,
  1Password) e código novo exigido a cada entrada.
- **Kill switch**: ao passar do limite de eventos de segurança (senhas erradas, códigos 2FA
  errados, força bruta), o sistema se **desliga**: derruba todas as sessões e responde 423
  até alguém reativar com a **senha offline** (ou `BOOR_UNLOCK_TOKEN` no servidor).
- **Conversor de links**: detecta a loja pelo domínio, limpa parâmetros de rastreio e aplica
  a tag de afiliado (Amazon, Mercado Livre, Shopee, AliExpress, Magalu, Americanas, KaBuM,
  Netshoes, Centauro, Carrefour, Dafiti… + lojas que você cadastrar).
- **Antifraude**: bloqueia oferta quando os comentários têm termos de risco ("fraude",
  "golpe", "roubo", "não entregaram", "falsificado"…) ou quando a reputação/vendas do
  vendedor ficam abaixo do mínimo da loja. Tudo fica registrado com o motivo.
- **Fotos reais do produto**: o robô pega a foto da oferta na API da loja; quando ela vem
  vazia, busca `og:image`/JSON-LD na página do produto e as APIs públicas (ex.: Mercado Livre
  `/items/{id}`), baixa a imagem para `/media` (sem hotlink bloqueado) e só usa um cartão com
  o nome do produto quando o link realmente não tem foto. Botões **Buscar foto no link** (por
  oferta) e **Buscar fotos reais** (todas) no painel.
- **Cupons**: capturados da API/texto da oferta, com botão **copiar** e botão
  **Ir para a oferta** que redireciona direto com a tag de afiliado.
- **Robô**: ciclos com pausas aleatórias, rotação de user-agent, renovação automática do
  access token via **refresh token** (grava o novo token e a expiração no banco).
- **Curadoria + Telegram**: o robô avalia o que compensa (desconto, reputação, vendas, cupom
  e procura do produto), monta a mensagem com preço riscado, cupom e link já com a tag, e
  publica no seu grupo do Telegram (foto quando há imagem). Nada bloqueado pelo antifraude é
  postado. Configure na aba **Telegram** (token do BotFather + ID do grupo, com botão de teste).
- **Critérios ajustáveis** (aba Robô → Critérios de postagem): desconto mínimo, nota de
  curadoria, reputação e vendas mínimas do vendedor, postagens por ciclo, intervalo do robô,
  palavras-chave que valem mais, palavras que você não quer ver e palavras de cautela. Há
  botão **Testar critérios** que mostra quantas ofertas passariam antes de salvar, e salvar
  recalcula a nota das ofertas já guardadas. Palavras de fraude alimentam o antifraude.
- **Painel**: ofertas, bloqueadas, cupons, lojas/APIs, robô e eventos de segurança.

## API (exemplos)

```bash
curl -X POST localhost:8077/api/convert -b cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"links":["https://www.amazon.com.br/dp/B0ABC"],"tag":"minhatag-20"}'

curl -X POST "localhost:8077/api/robot/run?store=amazon" -b cookies.txt
```

## Vercel (link público)

O projeto já está no GitHub: **https://github.com/maiconmonicavj-dot/boorlinkcopy**

1. Importar o repositório na Vercel (Framework: *Other*, sem build command).
2. Criar o banco na nuvem (Turso/libSQL tem plano gratuito) e definir:
   `BOOR_DB_URL=libsql://...` e `BOOR_DB_TOKEN=...` — o sistema usa esse banco
   automaticamente (adaptador libSQL em `app/db.py`); sem isso a Vercel usa `/tmp` e perde dados.
3. Definir também `BOOR_SECRET_KEY`, `BOOR_OFFLINE_PASSWORD`, `BOOR_UNLOCK_TOKEN`,
   `BOOR_COOKIE_SECURE=1`.
4. Copiar os dados que já existem aqui para a nuvem:
   `python scripts/migrate_to_turso.py` (com as duas variáveis do Turso no ambiente).
5. Robô: criar um Cron Job na Vercel chamando `POST /api/robot/run` a cada 20–30 min.
6. Fotos: com `VERCEL=1` o sistema guarda as URLs originais das lojas (não expiram);
   para guardar os arquivos, use Vercel Blob/S3 e defina `BOOR_IMG_DIR`.

Detalhes em `app/vercel_notes.md`.

## Subir na nuvem

1. Crie um servidor (Railway, Render, Fly.io, VPS com Docker) com Python 3.11.
2. `pip install -r requirements.txt` e rode `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
3. Defina `BOOR_SECRET_KEY`, `BOOR_OFFLINE_PASSWORD` (ou guarde a senha gerada) e
   `BOOR_COOKIE_SECURE=1` atrás de HTTPS.
4. Monte um volume persistente para `BOOR_DATA_DIR` (SQLite) — ou troque por Postgres.
5. Agende o robô: `python -m app.routine` a cada 20–30 minutos no cron, ou
   `python -m app.routine --loop` como serviço (ele já inclui pausas humanas aleatórias).
   Também funciona por `curl -X POST .../api/robot/run` (que coleta e publica).

## Próximos passos sugeridos

- Conectores oficiais por loja (Amazon PA-API, Mercado Livre, Shopee Open API, Awin/Rakuten).
- Fila de coleta (Celery/RQ) + Postgres para várias instâncias.
- Página pública de ofertas com SEO e links de afiliado.
- Envio automático das ofertas para WhatsApp/Telegram.
