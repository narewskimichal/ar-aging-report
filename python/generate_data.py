"""Generator syntetycznych eksportów z systemu ERP (należności, O2C).

Tworzy w folderze data/:
- customers.csv          kartoteka klientów (warunki płatności, limity, collector),
- fx_rates.csv           kursy walut na koniec miesiąca (do przeliczenia na EUR),
- open_items/            12 miesięcznych eksportów otwartych pozycji (aging),
- billing/               12 miesięcznych rejestrów wystawionych faktur.

Eksporty celowo zawierają typowe błędy z prawdziwych systemów (nagłówki raportu,
wiersz sumy, spacje i małe litery w ID klienta, duplikaty, brakujące terminy płatności).
Dane są w całości zmyślone, a stałe ziarno daje zawsze ten sam wynik.
"""

from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
N_CUSTOMERS = 40
SIM_START = pd.Timestamp('2025-05-01')
REPORT_MONTHS = pd.date_range('2025-11-30', '2026-10-31', freq='ME')
OUT_DIR = Path(__file__).resolve().parent.parent / 'data'

rng = np.random.default_rng(SEED)

COUNTRIES = {
    'PL': ('PLN', 'Sp. z o.o.'), 'DE': ('EUR', 'GmbH'), 'CZ': ('EUR', 's.r.o.'),
    'SK': ('EUR', 's.r.o.'), 'AT': ('EUR', 'GmbH'), 'NL': ('EUR', 'B.V.'), 'US': ('USD', 'Inc.'),
}
COUNTRY_WEIGHTS = [0.40, 0.20, 0.10, 0.08, 0.07, 0.07, 0.08]
NAME_PARTS_1 = ['Alvento', 'Brixon', 'Corvane', 'Delmaro', 'Estrel', 'Ferrion', 'Galvor', 'Helmar',
                'Isotra', 'Jorvik', 'Kalvex', 'Lumera', 'Marvon', 'Norvel', 'Ostrava', 'Pelmar',
                'Quintor', 'Rovanta', 'Selvic', 'Tarnex']
NAME_PARTS_2 = ['Logistics', 'Steel', 'Foods', 'Pharma', 'Automotive', 'Energy', 'Retail',
                'Plastics', 'Systems', 'Chemicals']
COLLECTORS = ['A. Nowak', 'P. Wiśniewski', 'K. Zielińska']
SEGMENTS = {'Key account': (6, 9.6), 'Standard': (4, 8.8), 'Small': (2, 8.0)}

# kursy: ile EUR za 1 jednostkę waluty (łagodne wahania wokół realistycznych poziomów)
FX_BASE = {'EUR': 1.0, 'PLN': 0.234, 'USD': 0.89}


def make_customers():
    rows = []
    names = rng.permutation([f'{a} {b}' for a in NAME_PARTS_1 for b in NAME_PARTS_2])[:N_CUSTOMERS]
    for i, name in enumerate(names, start=1):
        country = rng.choice(list(COUNTRIES), p=COUNTRY_WEIGHTS)
        currency, legal_form = COUNTRIES[country]
        segment = rng.choice(list(SEGMENTS), p=[0.2, 0.5, 0.3])
        profile = rng.choice(['good', 'slow', 'risky'], p=[0.6, 0.3, 0.1])
        rows.append({
            'customer_id': f'C{i:03d}',
            'customer_name': f'{name} {legal_form}',
            'country': country,
            'currency': currency,
            'segment': segment,
            'payment_terms_days': int(rng.choice([14, 30, 45, 60], p=[0.15, 0.5, 0.2, 0.15])),
            'collector': COLLECTORS[(i - 1) % 3],
            'profile': profile,
        })
    customers = pd.DataFrame(rows)
    # jeden duży klient, którego płatności pogarszają się w ostatnich miesiącach
    key = customers.index[customers['segment'] == 'Key account'][0]
    customers.loc[key, 'profile'] = 'deteriorating'
    return customers


def make_fx_rates():
    months = pd.date_range(SIM_START, REPORT_MONTHS[-1], freq='ME')
    rows = []
    for ccy, base in FX_BASE.items():
        walk = np.cumsum(rng.normal(0, 0.008, len(months))) if ccy != 'EUR' else np.zeros(len(months))
        for month_end, w in zip(months, walk):
            rows.append({'month': month_end.strftime('%Y-%m'), 'currency': ccy,
                         'eur_rate': round(base * (1 + w), 4)})
    return pd.DataFrame(rows)


def payment_delay(profile, invoice_date):
    """Opóźnienie zapłaty względem terminu (w dniach), zależne od profilu klienta."""
    if profile == 'good':
        return int(rng.normal(1, 4))
    if profile == 'slow':
        return int(rng.gamma(2.0, 9.0))
    if profile == 'risky':
        return int(rng.gamma(2.0, 30.0)) if rng.random() > 0.15 else None
    months_in = (invoice_date - pd.Timestamp('2026-04-01')).days / 30
    return int(rng.normal(5, 5)) if months_in < 0 else int(30 + 25 * months_in + rng.normal(0, 10))


def make_documents(customers, fx):
    fx_eur = fx.set_index(['month', 'currency'])['eur_rate']
    docs = []
    seq = {'INV': 0, 'CM': 0}
    for month_start in pd.date_range(SIM_START, REPORT_MONTHS[-1], freq='MS'):
        season = {12: 1.15, 8: 0.85}.get(month_start.month, 1.0)
        month_days = month_start.days_in_month
        for c in customers.itertuples():
            n_docs, log_mean = SEGMENTS[c.segment]
            rate = fx_eur[(month_start.strftime('%Y-%m'), c.currency)]
            for _ in range(rng.poisson(n_docs * season)):
                invoice_date = month_start + pd.Timedelta(days=int(rng.integers(0, month_days)))
                amount_eur = float(rng.lognormal(log_mean, 0.6))
                doc_type = 'CM' if rng.random() < 0.04 else 'INV'
                if doc_type == 'CM':
                    amount_eur = -amount_eur * 0.3
                seq[doc_type] += 1
                due_date = invoice_date + pd.Timedelta(days=c.payment_terms_days)
                disputed = doc_type == 'INV' and rng.random() < 0.03
                if doc_type == 'CM':
                    paid_date = invoice_date + pd.Timedelta(days=int(rng.integers(5, 45)))
                else:
                    delay = payment_delay(c.profile, invoice_date)
                    if disputed:
                        delay = None if rng.random() < 0.4 else int(rng.integers(60, 150))
                    paid_date = None if delay is None else due_date + pd.Timedelta(days=delay)
                partial_date = None
                if doc_type == 'INV' and paid_date is not None and rng.random() < 0.08:
                    partial_date = min(paid_date, due_date + pd.Timedelta(days=int(rng.integers(0, 20))))
                docs.append({
                    'invoice_no': f'{doc_type}-{invoice_date.year}-{seq[doc_type]:06d}',
                    'customer_id': c.customer_id,
                    'doc_type': doc_type,
                    'invoice_date': invoice_date,
                    'due_date': due_date,
                    'currency': c.currency,
                    'amount': round(amount_eur / rate, 2),
                    'dispute_flag': 'Y' if disputed else '',
                    'paid_date': paid_date,
                    'partial_date': partial_date,
                })
    return pd.DataFrame(docs)


def open_items_at(docs, month_end):
    issued = docs[docs['invoice_date'] <= month_end].copy()
    paid = issued['paid_date'].notna() & (issued['paid_date'] <= month_end)
    items = issued[~paid].copy()
    partial = items['partial_date'].notna() & (items['partial_date'] <= month_end)
    items['amount_open'] = np.where(partial, (items['amount'] * 0.5).round(2), items['amount'])
    items = items.rename(columns={'amount': 'amount_original'})
    return items[['customer_id', 'invoice_no', 'doc_type', 'invoice_date', 'due_date', 'currency',
                  'amount_original', 'amount_open', 'dispute_flag']].sort_values('invoice_date')


def add_data_issues(items):
    """Wprowadza typowe błędy z eksportów ERP."""
    items = items.copy()
    n = len(items)
    bad_id = rng.random(n) < 0.05
    items.loc[bad_id, 'customer_id'] = [cid.lower() + ' ' if rng.random() < 0.5 else ' ' + cid
                                        for cid in items.loc[bad_id, 'customer_id']]
    bad_ccy = rng.random(n) < 0.02
    items.loc[bad_ccy, 'currency'] = items.loc[bad_ccy, 'currency'].str.lower() + ' '
    missing_due = (rng.random(n) < 0.03) & (items['doc_type'] == 'INV')
    items['due_date'] = items['due_date'].astype(object)
    items.loc[missing_due, 'due_date'] = None
    duplicates = items.sample(frac=0.01, random_state=int(rng.integers(1_000_000)))
    return pd.concat([items, duplicates]).sort_values('invoice_date').reset_index(drop=True)


def format_export(df, date_cols, amount_cols):
    """Format jak w polskim eksporcie z ERP: daty dd.mm.rrrr, przecinek dziesiętny."""
    out = df.copy()
    for col in date_cols:
        out[col] = out[col].apply(lambda d: d.strftime('%d.%m.%Y') if pd.notna(d) else '')
    for col in amount_cols:
        out[col] = out[col].map(lambda x: f'{x:.2f}'.replace('.', ','))
    return out


def write_erp_export(df, path, title, run_date, total_col):
    lines = [f'{title};', f'Run date: {run_date:%d.%m.%Y};', '']
    body = df.to_csv(sep=';', index=False, lineterminator='\n').rstrip('\n').split('\n')
    total = f'{df[total_col].map(lambda s: float(s.replace(",", "."))).sum():.2f}'.replace('.', ',')
    footer = ['', ';'.join(['TOTAL'] + [''] * (df.columns.get_loc(total_col) - 1) + [total])]
    path.write_text('\n'.join(lines + body + footer) + '\n', encoding='utf-8-sig')


def main():
    (OUT_DIR / 'open_items').mkdir(parents=True, exist_ok=True)
    (OUT_DIR / 'billing').mkdir(parents=True, exist_ok=True)

    customers = make_customers()
    fx = make_fx_rates()
    docs = make_documents(customers, fx)

    # limit kredytowy: ok. 2,5-4 średniej miesięcznej sprzedaży klienta (w EUR)
    fx_eur = fx.set_index(['month', 'currency'])['eur_rate']
    docs['amount_eur'] = [a * fx_eur[(d.strftime('%Y-%m'), c)]
                          for a, d, c in zip(docs['amount'], docs['invoice_date'], docs['currency'])]
    months_total = docs['invoice_date'].dt.to_period('M').nunique()
    avg_sales = docs.groupby('customer_id')['amount_eur'].sum() / months_total
    customers['credit_limit_eur'] = [int(round(avg_sales[c] * rng.uniform(2.5, 4.0), -3))
                                     for c in customers['customer_id']]

    customers.drop(columns='profile').to_csv(OUT_DIR / 'customers.csv', sep=';', index=False,
                                             encoding='utf-8-sig')
    fx[fx['month'] >= REPORT_MONTHS[0].strftime('%Y-%m')].assign(
        eur_rate=lambda d: d['eur_rate'].map(lambda x: f'{x:.4f}'.replace('.', ','))
    ).to_csv(OUT_DIR / 'fx_rates.csv', sep=';', index=False, encoding='utf-8-sig')

    for month_end in REPORT_MONTHS:
        tag = month_end.strftime('%Y-%m')
        items = add_data_issues(open_items_at(docs, month_end))
        items = format_export(items, ['invoice_date', 'due_date'], ['amount_original', 'amount_open'])
        write_erp_export(items, OUT_DIR / 'open_items' / f'AR_open_items_{tag}.csv',
                         'Receivables - Open Items (Aging) Export', month_end, 'amount_open')

        billed = docs[docs['invoice_date'].dt.to_period('M') == month_end.to_period('M')]
        billed = billed[['invoice_no', 'customer_id', 'doc_type', 'invoice_date', 'currency', 'amount']]
        billed = format_export(billed, ['invoice_date'], ['amount'])
        write_erp_export(billed, OUT_DIR / 'billing' / f'AR_billing_{tag}.csv',
                         'Receivables - Billing Register', month_end, 'amount')

    print(f'Klienci: {len(customers)}, dokumenty: {len(docs)}, miesiące raportu: {len(REPORT_MONTHS)}')
    print(f'Pliki zapisane w {OUT_DIR}')


if __name__ == '__main__':
    main()
