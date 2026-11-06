# Deploy na Vercel — o que precisa ser feito

O projeto já vem com `vercel.json` e `index.py` prontos para o runtime `@vercel/python`.
O que **só o dono pode fazer** (dentro da conta Vercel):

1. **Importar o repositório**
   - vercel.com → *Add New… → Project* → *Import Git Repository* → `maiconmonicavj-dot/boorlinkcopy`.
   - Framework Preset: **Other**. Build Command e Output Directory: deixar vazio.
   - O `vercel.json` já aponta `index.py` como função e serve `/static/(.*)` de `app/web`.

2. **Banco de dados (importante)**
   - Na Vercel o disco é somente leitura, exceto `/tmp`, e `/tmp` é apagado a cada execução.
     Por isso o SQLite **não guarda dados na Vercel**.
   - Recomendado: **Turso** (libSQL, tem plano gratuito) — instalar o app `turso` no marketplace
     da Vercel e definir `BOOR_DB_URL` + `BOOR_DB_TOKEN`. Equivalentemente, Postgres
     (Neon/Supabase) com `DATABASE_URL`; o adaptador fica em `app/db.py` (`connect()`).
   - Enquanto não houver banco externo, o site funciona para demonstração, mas cadastros,
     ofertas e cupons se perdem entre execuções.

3. **Variáveis de ambiente** (Project → Settings → Environment Variables)
   - `BOOR_SECRET_KEY` — chave mestra (32+ bytes aleatórios) que criptografa refresh tokens e segredos 2FA.
   - `BOOR_OFFLINE_PASSWORD` — senha offline de reativação (define já na primeira execução).
   - `BOOR_UNLOCK_TOKEN` — token de emergência do servidor.
   - `BOOR_COOKIE_SECURE=1` — cookies só por HTTPS.
   - `BOOR_DATA_DIR=/tmp/boorlinkcopy` (padrão já aplicado quando `VERCEL=1`).

4. **Robô / cron**
   - A Vercel não roda processo em background. Crie um **Cron Job** (Pro) chamando
     `POST /api/robot/run` a cada 20–30 min com um header secreto, ou use o cron externo
     que preferir apontando para o mesmo endpoint.
   - O ciclo já inclui pausas humanas e postagem no Telegram.

5. **Imagens**
   - Fotos baixadas ficam em `/tmp` na Vercel (efêmeras). Para persistir, aponte
     `BOOR_IMG_DIR` para um volume/Blob (Vercel Blob/S3) ou mantenha as URLs originais das lojas
     (o sistema já aceita as duas formas).

> A alternativa mais simples e 100% funcional hoje: rodar o projeto em qualquer VPS/servidor
> com `python -m app.routine --loop` e docker-compose, onde o SQLite persiste normalmente.
