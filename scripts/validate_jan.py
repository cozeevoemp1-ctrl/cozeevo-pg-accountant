import pandas as pd

big = pd.read_excel('Statement-124563400000961-03-10-2026-20-15-08 (1)_extracted.xlsx')
big['Withdrawals'] = big['Withdrawals'].apply(lambda x: x if isinstance(x, float) else 0)
big['Deposits']    = big['Deposits'].apply(lambda x: x if isinstance(x, float) else 0)
jan_big = big[big['Transaction Date'].str.startswith('2026-01')].copy()

jan_file = pd.read_excel('Jan statement_extracted.xlsx')
jan_file['Withdrawals'] = jan_file['Withdrawals'].apply(lambda x: x if isinstance(x, float) else 0)
jan_file['Deposits']    = jan_file['Deposits'].apply(lambda x: x if isinstance(x, float) else 0)

print('=== JANUARY CROSS-CHECK ===')
print()
b_rows = len(jan_big);  j_rows = len(jan_file)
b_wd   = jan_big['Withdrawals'].sum();   j_wd   = jan_file['Withdrawals'].sum()
b_dep  = jan_big['Deposits'].sum();      j_dep  = jan_file['Deposits'].sum()

match_rows = "MATCH" if b_rows == j_rows else f"DIFF {j_rows-b_rows:+d}"
match_wd   = "MATCH" if abs(b_wd-j_wd) < 1 else f"DIFF Rs {j_wd-b_wd:+,.0f}"
match_dep  = "MATCH" if abs(b_dep-j_dep) < 1 else f"DIFF Rs {j_dep-b_dep:+,.0f}"

print(f'  Rows         | Big stmt: {b_rows:>4}  |  Jan PDF: {j_rows:>4}  |  {match_rows}')
print(f'  Withdrawals  | Big stmt: Rs {b_wd:>10,.0f}  |  Jan PDF: Rs {j_wd:>10,.0f}  |  {match_wd}')
print(f'  Deposits     | Big stmt: Rs {b_dep:>10,.0f}  |  Jan PDF: Rs {j_dep:>10,.0f}  |  {match_dep}')
print()

if b_rows != j_rows or abs(b_wd-j_wd) > 1 or abs(b_dep-j_dep) > 1:
    key = ['Transaction Date', 'Withdrawals', 'Deposits']
    in_jan_not_big = jan_file.merge(jan_big[key], on=key, how='left', indicator=True)
    in_jan_not_big = in_jan_not_big[in_jan_not_big['_merge'] == 'left_only']
    if len(in_jan_not_big):
        print(f'--- In Jan PDF but MISSING from big file ({len(in_jan_not_big)} rows) ---')
        for _, r in in_jan_not_big.iterrows():
            print(f'  {r["Transaction Date"]}  WD Rs {r["Withdrawals"]:>10,.0f}  DEP Rs {r["Deposits"]:>10,.0f}  {str(r["Description"])[:55]}')
        print()

    in_big_not_jan = jan_big.merge(jan_file[key], on=key, how='left', indicator=True)
    in_big_not_jan = in_big_not_jan[in_big_not_jan['_merge'] == 'left_only']
    if len(in_big_not_jan):
        print(f'--- In big file but MISSING from Jan PDF ({len(in_big_not_jan)} rows) ---')
        for _, r in in_big_not_jan.iterrows():
            print(f'  {r["Transaction Date"]}  WD Rs {r["Withdrawals"]:>10,.0f}  DEP Rs {r["Deposits"]:>10,.0f}  {str(r["Description"])[:55]}')
else:
    print('  All rows and totals match perfectly.')
