# Faboil — Registro Dogana · Memoria progressi

> App **teorica/didattica** ("per mia scienza, nulla sarà applicato in realtà") per la
> gestione di una stazione carburanti — Faboil / EUROSPEED Lusciano (**PV-2993**).
> File unico `registro-dogana/index.html`, aperto nel browser su PC Windows.
> Parsing Excel in-browser via **SheetJS** (CDN `xlsx@0.18.5`). Persistenza in
> `localStorage`. Nessun backend.

Ultimo aggiornamento: 2026-06-24.

---

## Regole di lavoro (sempre valide)
- **Ragioniamo piano e insieme.** Non portare mai fuori strada. Aspettare sempre
  l'input dell'utente. **Suggerire, non decidere** — decide l'utente.
- "recap" → riepiloga e parcheggia (non costruire). "scrivi"/"vai"/"continua" → costruisci.
- Valori del registro = **interi senza decimali**; erogazioni automatiche = **2 decimali, mai tonde**.
- La pagina Registro deve vedersi **senza scroll orizzontale**.

## Scopi principali
1. **Registro doganale**: scarico fisico carburante per pistola/giorno (da StoreSmart).
2. **Foglio commercialista**: corrispettivo = **vendite − fatturato**.

---

## Architettura dati (variabili globali in index.html)
- `STATE` — StoreSmart parsato: `{ days[], daily{pump:{day:litri}}, prezzoDay{day:{prod:prezzo}}, meta }`.
- `CARDSMART` — `{ byDayProd, byTessera{tess:{day:importo}}, byDayBase{day}, byDayImp{day}, meta }`.
- `ICAD`, `DKV` — `{ byDay{day:importo}, byDayScorp{day}, meta }` (da `parseFatt`).
- `CLIENTI[]` — anagrafica (da estesoL), ogni cliente `{ id, tipo PRE/POST, perc, saldo, saldoData,
  consumoMese, genAuto, tessere[{ id, targa, descrizione, prodotto, capienza, giorni[7], escludiFestivi,
  sospesa, prezzo, sconto, plafond, ... }] }`.
- `BUONI[]` — `{ id, clienteId, tessera, prodotto, day, litri, prezzo, sconto, totale, gen }`.
- `TRANSFERS[]` — trasferimenti interni `{ id, nome, cells{pump:{day:litri}} }`.
- `RICMAN` — ricariche prepagati manuali `{ seq, list[{id,clienteId,data,importo,num}] }`.
- `NETTO{pump:{day}}` — scarico netto calcolato da `recompute()` (≥0 garantito).
- Chiavi localStorage: `faboil_ss`, `faboil_cs`, `faboil_icad`, `faboil_dkv`,
  `faboil_clienti`, `faboil_ricariche_man`, `faboil_reg_<YYYY-MM>` (transfers+buoni del mese).

## Formule chiave
- **Registro netto** = grezzo StoreSmart − trasferimenti interni, poi engine buoni (`recompute()`).
  Regola d'oro: contatore mai indietro / scarico netto ≥ 0. Conservazione del prodotto.
- **Regola d'oro come vincolo INVALICABILE (guardiano unico `simulaNetto`):** ogni aggiunta/modifica
  manuale di buono e ogni aggiunta/aumento di travaso viene prima simulata; se renderebbe un netto < 0
  o lascerebbe un buono **short** (non piazzabile per intero), l'operazione è **rifiutata** con messaggio.
  Punti protetti: `addBuono`, `onAsCellClick` (modifica da Assegnazioni), `onRettInput` (travasi —
  bloccato anche se manda short un buono già inserito). Eliminare/ridurre è sempre permesso.
  La **generazione automatica** (opz. A) resta col razionamento per percentuale (water-filling), che
  già non viola mai la regola.
- **Due prezzi distinti (importante):**
  - **Vendite (corrispettivo)** = `STATE.venditeEur[day][prod]` = Σ della colonna **Importo €** di
    StoreSmart (già arrotondato per transazione) → vendite **ESATTE**, combaciano al centesimo col
    totale vendite reale. Fallback: Σ qta×prezzo se manca Importo; poi litri×prezzoDay per backup vecchi.
    NOTA: il riferimento "totale vendite" dell'utente È la somma della colonna Importo € di StoreSmart.
  - **Addebiti cartacei (buoni)** = prezzo di **fine giornata** (`prezzoDay` = ultima erogazione del
    giorno per prodotto). NON usare il prezzo esatto qui: i buoni si prezzano al riferimento di chiusura.
- **Corrispettivo/giorno** = vendite − (Card Smart + iCad + DKV + buoni).
- **Credito prepagato** = saldo@data + ricariche − (Card Smart Importo + buoni), dalla `saldoData` in poi.

### IVA / lordo-netto — VERIFICATO sui dati di giugno 2026
- StoreSmart prezzo pompa = **LORDO** (IVA inclusa): GASOLIO 1.948, VERDE 1.887, GPL 0.769.
- **Card Smart** "Prezzo Unitario" giugno = **identico** al prezzo pompa → **LORDO**.
  (Su dati 2025 vecchi era ~1.566 = sembrava netto: Card Smart può aver cambiato modalità.)
- **iCad** "Importo Transazione" = "Importo Fattura" = Imponibile + Iva → **LORDO**.
- **DKV** "Importo" = q×prezzo → **LORDO** (nessuna colonna IVA separata).
- **NIENTE moltiplicatore ×1.22.** Il corrispettivo è in LORDO ovunque.

### Sconti / maggiorazioni — SCORPORATI dal corrispettivo
Gli sconti/maggiorazioni delle fatture sono **esclusi** dal corrispettivo e mostrati nella
colonna "Sc./Magg.".
- **Card Smart**: corrispettivo = `byDayBase` = Σ(Qta×Prezzo) [base senza sconto].
  Scorporo = `byDayImp − byDayBase` (Importo − base). Giugno: base €80.849, scorporo +€854 (magg.).
- **DKV**: corrispettivo = colonna `Importo` (già base senza sconto). Scorporo = Σ(`Netto`−`Importo`).
  Giugno: base €22.908, scorporo −€399,51 (sconto).
- **iCad**: nessuna colonna sconto → scorporo 0. Giugno corrispettivo già lordo corretto.
- Convenzione segno scorporo: **+ maggiorazione, − sconto**.

## Stato funzionalità
| Sezione | Stato |
|---|---|
| Import StoreSmart → Registro | ✅ verificato at-the-liter (G3_2 diff 0) |
| Trasferimenti interni (regola d'oro) | ✅ |
| Buoni cartacei (engine day-first + water-filling) | ✅ |
| Generazione automatica buoni (tetto credito, % razionamento) | ✅ |
| Anagrafica clienti (import estesoL, PRE/POST, genAuto) | ✅ |
| Assegnazioni (griglia tessera×giorno, modifica/elimina) | ✅ |
| Ricariche prepagati manuali + ricevuta PDF | ✅ |
| Commercialista: Card Smart / iCad / DKV / buoni | ✅ |
| Sconti/maggiorazioni scorporati (CS, iCad, DKV) | ✅ |
| Backup/Restore JSON | ✅ |
| **POS / contanti (file CTRL CASSE)** | ❌ da fare |
| Ordine prepagati/postpagati su corrispettivo contanti | ❌ parcheggiato |

## Questioni risolte (revisione 2026-06-24)
1. **Doppio conteggio Card Smart + buoni** → **DECISO: nessuna modifica.** Per convenzione
   buoni e Card Smart non si sovrappongono mai (cliente o a tessera o a buono cartaceo).
2. **Sconto buoni non scorporato** → **DECISO + FATTO.** I buoni ora entrano nel fatturato a
   base piena `litri×prezzo`; lo sconto/magg (`totale−base`) va nella colonna Sc./Magg., fuori
   dal corrispettivo (come le fatture). Guardia: buono senza prezzo → base=totale, scorporo 0.
   Il **credito prepagato resta sul totale scontato** (consumo reale del credito). Impatto sui
   dati attuali: ~€0 (nessun buono ha sconto nel backup di giugno).
3. **Saldo prepagato senza data** → **DECISO + FATTO (opz. A).** Se un prepagato ha saldo senza
   `saldoData`: banner ⚠ nel box credito, e per i genAuto è trattato come "auto incompleto" →
   non generato finché non imposti la data. Non influisce sui corrispettivi (il credito non
   entra nel corrispettivo).

## Robustezza (fix difensivi, nessun impatto sui dati attuali)
- `csNum` tronca importi con migliaia puntate (`"1.030,65"` → 1.03) — dormiente perché gli
  importi arrivano come numeri. Da irrobustire (rimuovere i `.` se presenti sia `.` che `,`).
- `itNum` interpreta `"1.948"` stringa come 1948 — dormiente (i prezzi arrivano come numeri).
- `recompute`: aggiungere clamp `Math.max(0, work[p][d])` dopo i prelievi (residui float).
- `find(...includes...)` nei parser: preferire match esatto prima del match per sottostringa.
- Codice morto: `renderBuoniGrid`, `fillBuonoClienti`/`b-cliente-list`, `BCLI_LABELS`.

## File di riferimento (upload di sessione)
- StoreSmart erogazioni giugno 2026 (registro di partenza, contatori 0 al 31/5).
- Card Smart `RifornimentiPerPeriodo.xlsx` (col: Prezzo Unitario, Sconto, Quantita, Importo).
- iCad `ElencoTransazioniFatture.xlsx`, DKV `Erogazioni.xlsx`.
- Clienti `estesoL.xlsx` (fogli: Fine mese/Prepagati/Scontati/Punti).
