from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import datetime

pistole = ['G1_1','G1_2','G2_1','G2_2','G3_1','G3_2','G4_1','G4_2','G5_1','G5_2','G6_1','G6_2',
           'V1_3','V2_3','V3_3','V4_3','V5_3','V6_3','GPL1','GPL2','GPL3','GPL4','GPL5','GPL6']

wb = Workbook()
ws = wb.active
ws.title = 'REGISTRO GIUGNO'

arial = 'Arial'
hdr_fill = PatternFill('solid', start_color='1F4E78')
hdr_font = Font(name=arial, bold=True, color='FFFFFF', size=10)
date_font = Font(name=arial, bold=True, size=10)
cell_font = Font(name=arial, size=10)
input_font = Font(name=arial, size=10, color='0000FF')  # baseline = input blu
check_font = Font(name=arial, bold=True, size=10, color='1F4E78')
center = Alignment(horizontal='center')
thin = Side(style='thin', color='BFBFBF')
border = Border(left=thin,right=thin,top=thin,bottom=thin)

# assunzione scarico/pistola/giorno in cella separata (colonna AB)
asum_col = len(pistole)+3  # A=1 DATA, 2..25 pistole, 26 = scarico totale, then gap, 28 assunzione
# Layout: A=DATA, B..Y=24 pistole, Z=SCARICO TOT GIORNO, AB=assunzione
SCARICO_COL = len(pistole)+2  # = 26 -> Z
ASS_LABEL_COL = len(pistole)+4 # AB
ASS_VAL_COL = len(pistole)+5

# header row 1
ws.cell(row=1, column=1, value='DATA')
for j,p in enumerate(pistole):
    ws.cell(row=1, column=2+j, value=p)
ws.cell(row=1, column=SCARICO_COL, value='SCARICO TOT (lt)')
for c in range(1, SCARICO_COL+1):
    cell = ws.cell(row=1, column=c)
    cell.font = hdr_font; cell.fill = hdr_fill; cell.alignment = center; cell.border = border

# assunzione
ws.cell(row=1, column=ASS_LABEL_COL, value='Assunzione scarico/pistola/giorno (lt):').font = Font(name=arial, bold=True, size=10)
acell = ws.cell(row=2, column=ASS_VAL_COL, value=1000)
acell.font = input_font
ws.cell(row=1, column=ASS_VAL_COL, value='valore').font = Font(name=arial, size=9, italic=True)
ass_ref = f'${get_column_letter(ASS_VAL_COL)}$2'

# baseline row (31/05) = giorno 0, contatori a 0
r = 2
ws.cell(row=r, column=1, value=datetime.datetime(2026,5,31)).font = date_font
ws.cell(row=r, column=1).number_format = 'DD/MM/YYYY'
for j in range(len(pistole)):
    cc = ws.cell(row=r, column=2+j, value=0)
    cc.font = input_font  # lettura di partenza = input
    cc.number_format = '#,##0'; cc.alignment = center; cc.border = border
ws.cell(row=r, column=1).border = border
# scarico tot baseline blank
ws.cell(row=r, column=SCARICO_COL, value=None).border = border

# 30 giorni di giugno
for day in range(1,31):
    r = 2+day  # rows 3..32
    d = datetime.datetime(2026,6,day)
    dcell = ws.cell(row=r, column=1, value=d); dcell.font=date_font; dcell.number_format='DD/MM/YYYY'; dcell.border=border
    for j in range(len(pistole)):
        col = 2+j
        L = get_column_letter(col)
        # lettura = lettura giorno prima + assunzione scarico
        cc = ws.cell(row=r, column=col, value=f'={L}{r-1}+{ass_ref}')
        cc.font = cell_font; cc.number_format='#,##0'; cc.alignment=center; cc.border=border
    # scarico totale giorno = somma letture oggi - somma letture ieri
    sc = get_column_letter(SCARICO_COL)
    first = get_column_letter(2); last = get_column_letter(1+len(pistole))
    scell = ws.cell(row=r, column=SCARICO_COL, value=f'=SUM({first}{r}:{last}{r})-SUM({first}{r-1}:{last}{r-1})')
    scell.font=check_font; scell.number_format='#,##0'; scell.alignment=center; scell.border=border

# widths
ws.column_dimensions['A'].width = 12
for j in range(len(pistole)):
    ws.column_dimensions[get_column_letter(2+j)].width = 9
ws.column_dimensions[get_column_letter(SCARICO_COL)].width = 15
ws.column_dimensions[get_column_letter(ASS_LABEL_COL)].width = 32
ws.column_dimensions[get_column_letter(ASS_VAL_COL)].width = 10
ws.freeze_panes = 'B3'

wb.save('Registro_dogana_giugno_2026.xlsx')
print('saved')
