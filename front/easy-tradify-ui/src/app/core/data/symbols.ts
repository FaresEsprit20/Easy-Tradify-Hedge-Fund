export type SymbolCategory = 'forex' | 'metals' | 'indices' | 'crypto' | 'stocks';

export interface SymbolSeed {
  symbol: string;
  base: number;
  pip: number;
  category: SymbolCategory;
}

/** Deterministic pseudo-price so every symbol gets a stable, distinct seed
 * without hand-typing hundreds of base prices. */
function hashUnit(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  }
  return ((h >>> 0) % 1_000_000) / 1_000_000;
}

function priceIn(symbol: string, min: number, max: number): number {
  return min + hashUnit(symbol) * (max - min);
}

// --- Forex: majors, minors, and crosses across 20 real currency codes ---
const FX_EXPLICIT: Record<string, number> = {
  EURUSD: 1.0842, GBPUSD: 1.2731, USDJPY: 149.82, USDCHF: 0.8812, USDCAD: 1.3688,
  AUDUSD: 0.6512, NZDUSD: 0.5921, EURGBP: 0.8515, EURJPY: 162.44, EURCHF: 0.9554,
  EURAUD: 1.6649, EURCAD: 1.4841, EURNZD: 1.8312, GBPJPY: 190.64, GBPCHF: 1.1219,
  GBPAUD: 1.9548, GBPCAD: 1.7423, GBPNZD: 2.1502, AUDJPY: 97.55, AUDCHF: 0.5738,
  AUDCAD: 0.8914, AUDNZD: 1.0998, CADJPY: 109.44, CADCHF: 0.6438, NZDJPY: 88.71,
  NZDCHF: 0.5218, CHFJPY: 170.03, USDSEK: 10.92, USDNOK: 11.24, USDDKK: 6.93,
  USDPLN: 4.05, USDHUF: 360.2, USDCZK: 23.48, USDTRY: 34.15, USDZAR: 18.62,
  USDMXN: 17.08, USDSGD: 1.345, USDHKD: 7.81, USDCNH: 7.24, USDILS: 3.71,
  USDTHB: 34.52, EURSEK: 11.84, EURNOK: 12.18, EURPLN: 4.39, EURTRY: 37.03,
  EURZAR: 20.19,
};

// --- Metals ---
const METALS_EXPLICIT: Record<string, number> = {
  XAUUSD: 2648.3, XAGUSD: 65.0, XPTUSD: 985.4, XPDUSD: 1024.6,
  XAUEUR: 2442.1, XAGEUR: 59.95, XAUAUD: 4067.2, XAUGBP: 2079.6,
};

// --- Indices ---
const INDICES_EXPLICIT: Record<string, number> = {
  US500: 5924.1, US30: 43870.4, US2000: 2264.8, NAS100: 20841.5,
  UK100: 8285.4, GER40: 19420.7, FRA40: 7548.2, ESP35: 11982.6,
  ITA40: 34210.5, EU50: 4995.3, NETH25: 908.4, SWI20: 11890.2,
  JPN225: 39548.6, AUS200: 8215.9, HK50: 20184.3, CHINA50: 12405.7,
  SGP20: 3654.2, INDIA50: 24810.5, KOR200: 358.4, VIX: 14.2,
};

// --- Crypto: majors explicit, long tail hashed within a plausible band ---
const CRYPTO_EXPLICIT: Record<string, number> = {
  BTCUSD: 96420, ETHUSD: 3328.5, BNBUSD: 668.2, XRPUSD: 2.18, SOLUSD: 198.4,
};
const CRYPTO_TAIL = [
  'LTCUSD', 'BCHUSD', 'ADAUSD', 'DOGEUSD', 'DOTUSD', 'MATICUSD', 'AVAXUSD', 'LINKUSD',
  'TRXUSD', 'ATOMUSD', 'XLMUSD', 'ETCUSD', 'FILUSD', 'NEARUSD', 'APTUSD', 'ARBUSD',
  'OPUSD', 'SUIUSD', 'UNIUSD', 'AAVEUSD', 'MKRUSD', 'ALGOUSD', 'VETUSD', 'ICPUSD',
  'SANDUSD', 'MANAUSD', 'AXSUSD', 'EOSUSD', 'XTZUSD', 'THETAUSD', 'FTMUSD', 'GRTUSD',
  'RUNEUSD', 'CHZUSD', 'ENJUSD', 'ZECUSD', 'DASHUSD', 'XMRUSD', 'IOTAUSD', 'NEOUSD',
  'WAVESUSD', 'KSMUSD', 'CAKEUSD', 'CRVUSD', 'COMPUSD', 'SNXUSD', 'YFIUSD', 'BATUSD',
  'ZRXUSD', 'QTUMUSD', 'OMGUSD', 'LRCUSD', 'KAVAUSD', 'RVNUSD', 'SCUSD', 'ZILUSD',
  'ANKRUSD', 'CELOUSD', 'HBARUSD', 'EGLDUSD', 'FLOWUSD', 'GALAUSD', 'IMXUSD', 'APEUSD',
  'LDOUSD', 'STXUSD', 'INJUSD', 'TIAUSD', 'SEIUSD', 'PYTHUSD', 'JUPUSD', 'WLDUSD',
  'PEPEUSD', 'SHIBUSD', 'FETUSD', 'RNDRUSD',
];

// --- Stocks: real, widely-known CFD tickers (US large/mid caps + international ADRs) ---
const STOCKS = [
  'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'META', 'NVDA', 'TSLA', 'BRK.B', 'JPM',
  'V', 'UNH', 'HD', 'PG', 'MA', 'XOM', 'JNJ', 'MRK', 'ABBV', 'COST',
  'AVGO', 'CVX', 'PEP', 'KO', 'ADBE', 'WMT', 'CSCO', 'MCD', 'CRM', 'BAC',
  'TMO', 'ACN', 'LIN', 'ABT', 'DHR', 'NFLX', 'TXN', 'NKE', 'PM', 'NEE',
  'RTX', 'UPS', 'HON', 'QCOM', 'UNP', 'LOW', 'INTC', 'IBM', 'CAT', 'GE',
  'AMD', 'SPGI', 'INTU', 'ISRG', 'AMGN', 'PLD', 'NOW', 'DE', 'BKNG', 'AXP',
  'GS', 'BLK', 'MDT', 'SBUX', 'GILD', 'ADP', 'MMC', 'LMT', 'SYK', 'MDLZ',
  'TJX', 'VRTX', 'CVS', 'C', 'ADI', 'REGN', 'MO', 'PYPL', 'ETN', 'ZTS',
  'SO', 'BDX', 'PGR', 'CB', 'DUK', 'BSX', 'EQIX', 'APD', 'AON', 'ITW',
  'CL', 'SLB', 'MU', 'CSX', 'HUM', 'NOC', 'WM', 'FCX', 'EOG', 'MCK',
  'ORCL', 'SHW', 'EMR', 'ROP', 'MPC', 'PSX', 'MAR', 'PANW', 'KLAC', 'GM',
  'F', 'DIS', 'T', 'VZ', 'PFE', 'ABNB', 'UBER', 'LYFT', 'SNAP', 'PINS',
  'SQ', 'SHOP', 'SPOT', 'ZM', 'DOCU', 'CRWD', 'SNOW', 'PLTR', 'RBLX', 'COIN',
  'HOOD', 'SOFI', 'RIVN', 'LCID', 'NIO', 'XPEV', 'LI', 'BABA', 'JD', 'PDD',
  'BIDU', 'TCEHY', 'TSM', 'ASML', 'SAP', 'NVO', 'AZN', 'TM', 'HMC', 'SONY',
  'ORLY', 'ROST', 'DG', 'DLTR', 'YUM', 'CMG', 'DPZ', 'BKNG', 'EXPE', 'TRIP',
  'MAR', 'HLT', 'H', 'WYNN', 'MGM', 'LVS', 'CCL', 'RCL', 'NCLH', 'DAL',
  'UAL', 'AAL', 'LUV', 'ALK', 'BA', 'GD', 'LHX', 'TDG', 'HII', 'TXT',
  'PH', 'DOV', 'IEX', 'XYL', 'AME', 'ROK', 'FTV', 'IR', 'CMI', 'PCAR',
  'WAB', 'JCI', 'CARR', 'OTIS', 'MAS', 'VMC', 'MLM', 'NUE', 'STLD',
  'X', 'CLF', 'AA', 'FCX', 'NEM', 'GOLD', 'AEM', 'KGC', 'WPM', 'RGLD',
  'SLV', 'SCHW', 'MS', 'WFC', 'USB', 'PNC', 'TFC', 'COF', 'DFS', 'SYF',
  'ALLY', 'AIG', 'MET', 'PRU', 'AFL', 'TRV', 'ALL', 'HIG', 'CINF', 'WRB',
  'CBOE', 'CME', 'ICE', 'NDAQ', 'MCO', 'MSCI', 'FDS', 'MKTX', 'TROW', 'BEN',
  'IVZ', 'AMP', 'RJF', 'STT', 'BK', 'NTRS', 'PYPL', 'FIS', 'FISV', 'GPN',
  'JKHY', 'BR', 'CDNS', 'SNPS', 'ANSS', 'ADSK', 'PTC', 'TYL', 'CTXS', 'WDAY',
  'TEAM', 'HUBS', 'ZS', 'OKTA', 'DDOG', 'NET', 'FTNT', 'CYBR', 'S',
  'MDB', 'ESTC', 'CFLT', 'GTLB', 'PATH', 'AI', 'U', 'RBLX', 'DASH', 'ABNB',
  'ETSY', 'EBAY', 'W', 'CHWY', 'CVNA', 'CPNG', 'MELI', 'SE', 'GRAB', 'BEKE',
  'PSA', 'SPG', 'O', 'DLR', 'AMT', 'CCI', 'SBAC', 'WY', 'AVB', 'EQR',
  'ESS', 'MAA', 'UDR', 'CPT', 'INVH', 'AMH', 'EXR', 'CUBE', 'LSI', 'PLD',
  'D', 'EXC', 'AEP', 'SRE', 'XEL', 'ED', 'EIX', 'PEG', 'WEC', 'ES',
  'AWK', 'ATO', 'CMS', 'DTE', 'ETR', 'FE', 'NI', 'PPL', 'AEE', 'LNT',
  'CNP', 'EVRG', 'PNW', 'NRG', 'VST', 'CEG', 'GEV', 'ENPH', 'SEDG', 'FSLR',
  'RUN', 'PLUG', 'BE', 'CHPT', 'BLNK', 'QS', 'FCEL', 'CLNE', 'AMRC', 'ARRY',
];

function buildForex(): SymbolSeed[] {
  return Object.entries(FX_EXPLICIT).map(([symbol, base]) => ({
    symbol,
    base,
    pip: symbol.includes('JPY') ? 0.01 : 0.0001,
    category: 'forex' as const,
  }));
}

function buildMetals(): SymbolSeed[] {
  return Object.entries(METALS_EXPLICIT).map(([symbol, base]) => ({
    symbol,
    base,
    pip: base > 500 ? 0.1 : 0.01,
    category: 'metals' as const,
  }));
}

function buildIndices(): SymbolSeed[] {
  return Object.entries(INDICES_EXPLICIT).map(([symbol, base]) => ({
    symbol,
    base,
    pip: 1,
    category: 'indices' as const,
  }));
}

function buildCrypto(): SymbolSeed[] {
  const explicit = Object.entries(CRYPTO_EXPLICIT).map(([symbol, base]) => ({
    symbol,
    base,
    pip: base > 100 ? 1 : 0.0001,
    category: 'crypto' as const,
  }));
  const tail = CRYPTO_TAIL.map((symbol) => {
    const base = Math.round(priceIn(symbol, 0.01, 220) * 10000) / 10000;
    return { symbol, base, pip: base > 100 ? 1 : 0.0001, category: 'crypto' as const };
  });
  return [...explicit, ...tail];
}

function buildStocks(): SymbolSeed[] {
  return Array.from(new Set(STOCKS)).map((symbol) => ({
    symbol,
    base: Math.round(priceIn(symbol, 8, 480) * 100) / 100,
    pip: 0.01,
    category: 'stocks' as const,
  }));
}

export const SYMBOL_UNIVERSE: SymbolSeed[] = [
  ...buildForex(),
  ...buildMetals(),
  ...buildIndices(),
  ...buildCrypto(),
  ...buildStocks(),
];

/** O(1) lookup — the live-tick loop touches every watchlist row on every
 * tick, so a linear `.find()` over ~500 symbols is worth avoiding. */
export const SYMBOL_MAP: ReadonlyMap<string, SymbolSeed> = new Map(SYMBOL_UNIVERSE.map((s) => [s.symbol, s]));

export const CATEGORY_LABELS: Record<SymbolCategory, string> = {
  forex: 'Forex',
  metals: 'Metals',
  indices: 'Indices',
  crypto: 'Crypto',
  stocks: 'Stocks',
};
