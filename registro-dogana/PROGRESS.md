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
- **Ordine motore: BUONI poi TRAVASI** (`simulaNetto`). 1) i buoni spostano vendite sul grezzo;
  2) i travasi sottraggono dal registro-coi-buoni. Il **tetto del travaso per cella = netto
  post-buoni** (`REGBUONI[p][d]`), non il grezzo (es. se G1_1 mostra 1.120, si rettifica fino a 1.120).
- **Buono su SINGOLA pistola:** ogni buono lavora sulla pistola con **più margine** per prima;
  aggiunge i litri al **suo** giorno su **quella** pistola (può superare il grezzo, è normale) e li
  preleva dai giorni-sorgente **della stessa pistola** nell'ordine **festivi → sabati → giorno stesso
  del buono → altri normali**, in modo proporzionale, pavimento **100 L** (`FLOOR_LT`). Passa alla
  pistola successiva solo se la prima non basta. Il "giorno stesso" è soddisfatto dalle vendite
  proprie di X (nessun movimento). **Totale conservato** (i buoni spostano, non tolgono).
- **Regola d'oro come vincolo INVALICABILE (guardiano unico `simulaNetto`):** ogni aggiunta/modifica
  manuale di buono e ogni aggiunta/aumento di travaso viene prima simulata; se renderebbe un netto < 0
  o lascerebbe un buono **short** (non piazzabile per intero), l'operazione è **rifiutata** con messaggio.
  Punti protetti: `addBuono`, `onAsCellClick` (modifica da Assegnazioni), `onRettInput` (travasi —
  bloccato anche se manda short un buono già inserito). Eliminare/ridurre è sempre permesso.
  La **generazione automatica** (opz. A) resta col razionamento per percentuale (water-filling), che
  già non viola mai la regola.
- **Due prezzi distinti (importante):**
  - **Vendite GREZZE** = `STATE.venditeEur[day][prod]` = Σ colonna **Importo €** StoreSmart (esatte,
    combaciano col riferimento utente = somma colonna Importo €).
  - **Vendite NETTE (usate nel corrispettivo)** = vendite grezze **scalate per (litri netti / litri
    grezzi)** del giorno → **travasi e buoni MUOVONO le vendite**. Senza travasi/buoni: netto=grezzo →
    nette=grezze=esatte. Travaso → vendite del giorno ↓; buono → sposta vendite sul suo giorno (così
    "copre" il suo fatturato) prendendole dai festivi; totale conservato dai buoni.
    `corrispettivo = vendite NETTE − fatturato`. Commercialista mostra entrambe (grezze + nette) —
    colonne complete in sviluppo, poi si trimmano.
  - **Addebiti cartacei (buoni)** = prezzo di **fine giornata** (`prezzoDay` = ultima erogazione del
    giorno per prodotto). NON usare il prezzo esatto qui: i buoni si prezzano al riferimento di chiusura.
- **Corrispettivo/giorno** = vendite − (Card Smart + iCad + DKV + buoni).
- **Credito prepagato** = saldo@data + ricariche − (Card Smart Importo + buoni), dalla `saldoData` in poi.

### CRISTALLIZZAZIONE (registro cartaceo scritto → giorni congelati)
Flag `CRISTAL` (data) + snapshot `CRISTALNET` (netto dei giorni ≤ data, fotografato al momento).
Giorni **≤ CRISTAL = congelati** (`isCristal(day)`):
- **Registro fisso**: usa lo snapshot, non si ricalcola.
- **Niente travasi** sui congelati (cella disabilitata 🔒; guardia in `onRettInput`).
- **Buoni sui congelati = solo cassa** (no movimento litri): `bres.cash=true`, riducono il contante,
  bloccati dalla 2ª regola se lo porterebbero < 0.
- **Buoni sui giorni liberi NON attingono dai congelati** (sorgenti escludono `isCristal`).
- UI: pagina Registro, "🔒 Cristallizza fino al [data] · Blocca/Sblocca"; lucchetto sui giorni
  congelati nel registro e nei trasferimenti. Persistito in `faboil_reg_<mese>`.

### DUE REGOLE D'ORO (un buono/travaso deve rispettarle ENTRAMBE)
1. **Fisica/registro**: contatore mai indietro → scarico netto ≥ 0 (implementata).
2. **Cassa/commercialista**: **corrispettivo (= contante senza POS) mai negativo** — implementata sui
   controlli manuali (`addBuono`, `onAsCellClick`, `onRettInput`) via `corrViolato()`. Senza POS il
   contante coincide col corrispettivo; con CTRL CASSE diventerà `corrispettivo − POS-su-corrispettivi`.
   NB: la **generazione automatica** non applica ancora la 2ª regola (da fare).
Un buono o un travaso che violerebbe una delle due viene **bloccato**.

### Corrispettivo CONTANTI (modello a strati — da implementare con CTRL CASSE)
Esempio 1 giugno: vendite 10.000 (10.000 L×1€) − CS 5.000 − iCad 1.000 − DKV 1.000 = **corrispettivo 3.000**;
con un buono di 1.000 il "non toccabile" sale e il corrispettivo scende a 2.000.
- **🔒 Non toccabili**: Card Smart, iCad, DKV, buoni, **POS-su-corrispettivi**.
- **✅ Toccabile (contante)** = Corrispettivo − POS-su-corrispettivi → **deve restare ≥ 0**. Solo questo
  contante è **spostabile** (buoni su altri giorni) o **rettificabile** (travasi).
- **POS-su-fatture** (POS che paga fatture alla pompa, NON è corrispettivo) si ricava dai file:
  - **iCad**: tutte TRANNE UTA (UTA = clienti con "UTA" nel nome/Numero Fattura, pagate Bonifico;
    le non-UTA sono tutte "Carta di pagamento"). Giugno: non-UTA €9.860,85 · UTA €4.895,22.
  - **Card Smart**: righe con **Tipologia Cliente = "Sconto" o "Punti"** (colonna C / "Tipologia Cliente",
    cella unita). Giugno: Sconto €38.289,33 · Punti €0. (Post Pagati/Pre Pagati NON sono POS.)
  - Totale POS-su-fatture giugno = €48.150,18.
- **POS-su-corrispettivi** = POS totale (da **CTRL CASSE**, ancora mancante) − POS-su-fatture.
- **Contante** = Corrispettivo − POS-su-corrispettivi. Buoni/travasi limitati a "contante ≥ 0".

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
| Responsive telefono (CSS, opz. A) | ✅ tab scrollabili, tabelle con scroll orizz. e colonna DATA congelata, tocchi grandi |
| Ricerca clienti fluida su telefono | ✅ debounce 140ms + event delegation (1 listener invece di ~700/keystroke) |
| **POS nel commercialista (file resoconto vendite)** | ✅ fatto: import sola lettura, filtro account Lusciano/Casaluce, colonne POS / Sc. pompa / Contanti |
| **Travasi/buoni subordinati a "contanti ≥ 0"** | ✅ fatto: `corrViolato` usa il contante reale (corr − POS + sconto-alla-pompa) quando il POS è caricato, altrimenti fallback corr≥0 |
| **Controllo benzinai (per operatore, CTRL CASSE)** | ❌ da fare (separato dal commercialista): scheda+nome editabili, multi-distributore, Servito(StoreSmart per tessera) − POS(per account) |
| Colonna scorporo separata per i buoni | ✅ fatto: due colonne "Sc./Magg. fatt." e "Sc./Magg. buoni" |
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

## Robustezza — FATTO (verificato: stessi totali parser al centesimo)
- `itNum`/`csNum` ora robusti: "1.234,56" (mig.+dec.), "1,566", "1.948" gestiti correttamente.
- `find()` nei parser: match esatto prima del match per sottostringa.
- Codice morto rimosso: `renderBuoniGrid`, `fillBuonoClienti`/`b-cliente-list`, `BCLI_LABELS`.
- (Il clamp `Math.max(0,...)` è già nel nuovo `simulaNetto` FASE 2.)

## POS / Contanti nel commercialista — FATTO (2026-06-25)
- **Import POS** dal file *resoconto vendite* (`parsePos`): legge Data / Account / Importo,
  aggrega per **account** (= operatore) e per giorno. **Sola lettura** (il POS è un dato di
  fatto, non si modifica). Card import "POS — Incassato" in Importazioni.
- **Filtro distributore**: il file mescola Lusciano + Casaluce. Dopo l'import si mostrano i
  chip degli account (con totale €); cliccandoli si escludono quelli di Casaluce. La
  selezione (`POSLUS`) è salvata in `localStorage` (`faboil_pos`, `faboil_poslus`).
  `posDay(d)` somma solo gli account selezionati (Lusciano).
- **Sconto-alla-pompa** (POS-su-fatture, automatico) = **iCad non-UTA** + **Card Smart
  tipologia Sconto/Punti**. `parseFatt` per iCad ora scorpora le righe UTA (cliente contiene
  "UTA", incassate a parte) → `byDayNonUta`. `parseCardSmart` accumula `byDayScontoPunti`
  (tipologia cliente Sconto/Punti, con fill-down sulle celle unite).
- **Formula contanti** (verificata sull'esempio dell'utente: 10000 vendite −7000 fatt
  = 3000 corr, POS 1500 di cui 500 alla pompa → 1000 contante margine):
  `CONTANTI = Corrispettivo − POS + Sconto-alla-pompa`. Il POS andato su fatture pagate alla
  pompa non deve abbassare i contanti, perciò si ri-aggiunge.
- **Colonne commercialista**: aggiunte **POS**, **Sc. pompa**, **Contanti** (oltre a
  Corrispettivo). Export Excel aggiornato di conseguenza.
- **2ª regola d'oro** ora sui contanti reali: `corrViolato` blocca buoni/travasi che rendono
  `CONTANTI < 0` quando il POS è caricato; senza POS resta il fallback `Corrispettivo ≥ 0`.
- Verifica jsdom: 5/5 check OK (modello completo, filtro Casaluce, regola d'oro contanti,
  parsePos, fallback senza POS).

## Sezione Importazioni — riordino (2026-06-25)
- Da 7 box impilati a **una sola card "Importa un file"**: si trascina un .xlsx e il tipo
  viene **riconosciuto in automatico** (`detectType` per firme d'intestazione):
  POS (`account`+`prezzo (lordo)`), iCad (`data transazione`+`importo transazione`),
  DKV (`netto`+`cliente`+`sconto/magg.`), Card Smart (`prodotto`+tessera/tipologia/prezzo unit.),
  StoreSmart (`pompa`+`data rifornimento`), Clienti (`idcliente`+`ragione` o fogli estesoL).
- Sotto, **elenco "File caricati"**: Tipo · File · Caricato il · Copre fino a (periodo), con ✕
  per rimuovere una fonte. Stato in `faboil_srcmeta`; `restoreImports` ricostruisce l'elenco
  (sintetizza i metadati per i backup vecchi). Verificato: 6/6 file riconosciuti, ripristino OK.
- `cellDay` ora legge anche le date "1 giu 2026, 00:00" (mesi italiani) usate dal resoconto POS.

## Controllo casse — FATTO v2 (2026-06-25)
- Scheda **Controllo casse** come **elenco di schede gestore auto-rilevate**.
- **Scheda gestore = tessera (7 cifre) presente in StoreSmart e ASSENTE dall'anagrafica
  clienti (estesoL).** (Criterio corretto: il primo tentativo "non in Card Smart" sbagliava —
  es. tessere Sabatino 3331xxx assenti da Card Smart ma clienti veri.) Verificato: dà
  esattamente le 10 schede 4273xxx, zero falsi positivi; una clandestina (badge non a
  registro clienti) emergerebbe da sola. Richiede StoreSmart + anagrafica clienti.
- **Elenco** (totali periodo, una riga per scheda): N. tessera · Nome (editabile, precompilato
  da `SCHEDE_NOTE`) · Account POS (tendina, abbinamento manuale) · Servito · POS · DROP ·
  Monete · Sospese · UTA · DKV · **= TOT**. Riga **rossa + ⚠** = scheda non riconosciuta
  (possibile clandestina). `TOT = Servito − POS − DROP − Monete − Sospese − UTA − DKV` (≈0).
- **Dettaglio giornaliero** per scheda: DROP/Monete/Sospese/UTA/DKV **a mano per giorno**.
  - **Sospese** = transazioni autorizzate col badge gestore, poi assegnate al cliente in Card
    Smart e scalate dal badge → non sono contante dovuto.
  - **UTA/DKV** = riforniti con carta carburante (fattura a UTA/DKV) → non contante né POS.
- **Convalida giornaliera UTA/DKV**: per giorno confronta Σ UTA inserita vs **iCad UTA**
  (`byDay − byDayNonUta`) e Σ DKV inserita vs **file DKV**; i giorni con Δ>0,50 € = anomalia.
- **Servito** = `STATE.servitoTess[scheda][day]` (Σ Importo €, **incluso ADBLUE**, prima dei
  filtri pompa). **POS** = per account abbinato, sui giorni del registro.
- **Filtro Lusciano nel commercialista**: tolti i chip POS. Ora `posSel(account)` = l'account è
  abbinato a una scheda gestore nel controllo casse (Casaluce escluso da sé perché non ha
  scheda in StoreSmart); finché non abbini nulla → tutti. Auto-abbino le 8 schede note il cui
  nome combacia col POS; Carmine e Cantile (nome invertito) li abbini a mano.
- Stato in `localStorage` (`faboil_casse`). Verifica jsdom: 10 schede, Casaluce escluso,
  posDay filtrato, convalida OK; regressione POS 5/5.
- **PENDENTE**: parametrizzazione per **turno (giorno + ora)** — ogni operatore ha turni diversi
  (anche a cavallo di mezzanotte). Serve conservare l'orario delle transazioni; da definire come
  l'utente descrive i turni. Il totale periodo per scheda è indipendente dal turno.

## File di riferimento (upload di sessione)
- StoreSmart erogazioni giugno 2026 (registro di partenza, contatori 0 al 31/5).
- Card Smart `RifornimentiPerPeriodo.xlsx` (col: Prezzo Unitario, Sconto, Quantita, Importo).
- iCad `ElencoTransazioniFatture.xlsx`, DKV `Erogazioni.xlsx`.
- Clienti `estesoL.xlsx` (fogli: Fine mese/Prepagati/Scontati/Punti).
