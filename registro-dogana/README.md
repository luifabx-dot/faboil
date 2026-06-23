# Registro Dogana — Carico/Scarico Carburante (Faboil Lusciano)

Generatore del **registro UTF/dogana** per il carico-scarico carburante della
stazione di servizio Faboil di Lusciano (CE).

## Contenuto

| File | Descrizione |
|------|-------------|
| `build_reg.py` | Script Python (openpyxl) che genera il file Excel del registro. |
| `Registro_dogana_giugno_2026.xlsx` | Esempio di registro generato (giugno 2026). |

## Cosa genera

Un foglio Excel `REGISTRO GIUGNO` con:

- **24 pistole** di erogazione:
  - 12 codici `G1_1 … G6_2` (benzina/gasolio)
  - 6 codici `V1_3 … V6_3`
  - 6 codici `GPL1 … GPL6`
- Riga **baseline `31/05/2026`** con i contatori di partenza (default `0`, in blu = input da compilare).
- **30 righe** per i giorni di giugno: ogni lettura =
  `lettura del giorno precedente + assunzione scarico`.
- Cella **assunzione scarico** (`AC2`, default `1000` lt/pistola/giorno): cambiandola
  si ricalcolano tutte le letture progressive.
- Colonna **SCARICO TOT (lt)**: somma letture di oggi − somma letture di ieri.

Formattazione: intestazioni blu, bordi, formato data, larghezze colonne e
riquadri bloccati (`freeze_panes`).

## Come si usa

```bash
pip install openpyxl
python build_reg.py
# -> crea Registro_dogana_giugno_2026.xlsx nella cartella corrente
```

Poi in Excel/LibreOffice:
1. Inserire i **contatori reali di partenza** nella riga baseline (31/05).
2. Regolare l'**assunzione scarico** in `AC2` se diversa da 1000 lt.
3. Le letture giornaliere e lo scarico totale si calcolano automaticamente.

## Personalizzazione

Nello script si possono modificare:
- l'elenco `pistole` (numero e codici degli erogatori);
- mese e anno (le date in `build_reg.py`);
- il valore di default dell'assunzione scarico.
