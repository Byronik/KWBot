# KWBot – Guida Docker

## Struttura cartelle sul PC

Dopo aver copiato i file, la struttura deve essere:

```
kwb_v3/                      ← cartella del progetto
├── Dockerfile
├── docker-compose.yml
├── main.py
├── requirements.txt
├── src/
│   ├── bot.py
│   ├── charts.py
│   ├── config.py
│   ├── db.py
│   ├── logger.py
│   ├── modbus_reader.py
│   ├── registers.py
│   ├── alarms.py
│   └── query.py
│
└── kwbot_data/              ← VOLUME ESTERNO (persiste tra riavvii)
    └── config.ini           ← da configurare prima dell'avvio
```

Il DB e i log vengono creati automaticamente dentro `kwbot_data/` al primo avvio.

---

## Passo 1 – Configura config.ini

Apri `kwbot_data/config.ini` e modifica:

```ini
[telegram]
bot_token   = 123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
allowed_ids = 111222333        ; il tuo Telegram user ID
```

Per trovare il tuo user ID Telegram: scrivi a `@userinfobot` su Telegram.

---

## Passo 2 – Primo avvio (Windows con Docker Desktop)

Apri PowerShell o il Terminale di Windows nella cartella `kwb_v3/`:

```powershell
# Costruisce l'immagine e avvia il container in background
docker compose up -d --build
```

Al primo avvio Docker scarica Python e installa le dipendenze (~2-3 minuti).
Dai secondi avvii sarà immediato (usa la cache).

---

## Passo 3 – Verifica che funzioni

```powershell
# Controlla che il container sia "Up"
docker compose ps

# Vedi i log in tempo reale (Ctrl+C per uscire)
docker compose logs -f

# Controlla gli ultimi valori letti dal DB
docker compose exec kwbot python main.py --status
```

---

## Riavvio automatico al boot di Windows

Il `restart: unless-stopped` nel docker-compose.yml fa già il lavoro:
- Docker Desktop su Windows si avvia con Windows (se configurato così)
- Il container riparte automaticamente dopo ogni riavvio del PC
- L'unico caso in cui NON riparte è se lo fermi tu manualmente con `docker compose down`

**Verifica che Docker Desktop sia configurato per avviarsi con Windows:**
1. Apri Docker Desktop → Settings → General
2. Spunta **"Start Docker Desktop when you log in"**

---

## Comandi utili quotidiani

```powershell
# Ferma il container (non lo elimina, i dati sono salvi)
docker compose stop

# Riavvia il container
docker compose restart

# Ferma e rimuove il container (i dati in kwbot_data/ restano intatti)
docker compose down

# Riavvia con rebuild (dopo aggiornamento del codice)
docker compose up -d --build

# Interroga il DB manualmente
docker compose exec kwbot python main.py query status
docker compose exec kwbot python main.py query history boiler_temp_actual --days 7
docker compose exec kwbot python main.py query bot-events --limit 20

# Esegui un singolo poll di test (verifica connessione caldaia)
docker compose exec kwbot python main.py --once

# Controlla i log degli ultimi 100 messaggi
docker compose logs --tail=100
```

---

## Migrazione da Windows a Linux

I dati sono tutti nella cartella `kwbot_data/` — basta copiarla.

```bash
# Sul PC Linux, nella cartella del progetto:
docker compose up -d --build
```

Nessuna differenza di configurazione: lo stesso docker-compose.yml e lo stesso
config.ini funzionano identici su entrambi i sistemi operativi.

**Nota su network_mode: host:**
- Su Linux funziona nativamente (accesso diretto alla rete locale)
- Su Windows/Docker Desktop funziona grazie al bridge automatico di Docker Desktop
- Su entrambi raggiunge la caldaia su 192.168.50.100 senza configurazione aggiuntiva

---

## Backup dei dati

I dati da fare backup sono solo quelli in `kwbot_data/`:

```powershell
# Esempio backup su Windows
xcopy kwb_v3\kwbot_data\ backup\kwbot_data\ /E /I /Y
```

Il DB SQLite può essere copiato mentre il container è fermo (`docker compose stop`).
Con WAL mode abilitata, è sicuro copiarlo anche a caldo purché non ci siano
write in corso (rischio minimo con polling ogni 5 minuti).

---

## Troubleshooting

**Container si riavvia in loop (status: Restarting)**
```powershell
docker compose logs --tail=50
```
Causa più comune: `config.ini` mancante o token Telegram non valido.

**"Cannot connect to 192.168.50.100:502"**
- Verifica che il PC e la caldaia siano sulla stessa rete
- Verifica che Modbus sia abilitato sulla caldaia (Comfort 4: `modbus_ein = 1`)
- Su Windows: verifica che il firewall non blocchi la porta 502

**Vedere il DB con un client SQLite esterno**
Il file `kwbot_data/kwb_data.db` è un normale SQLite — apribile con
DB Browser for SQLite o qualsiasi altro client direttamente dall'host.
