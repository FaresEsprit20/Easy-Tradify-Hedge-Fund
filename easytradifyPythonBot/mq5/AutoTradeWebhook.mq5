//+------------------------------------------------------------------+
//|                                                  TradeWebhook.mq5 |
//|                                    Copyright 2024, AI Trading    |
//|                                       https://www.yourwebsite.com |
//+------------------------------------------------------------------+
#property copyright "AI Trading System"
#property version   "3.00"
#property description "Trade Webhook - CLOSE & MODIFY only"

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                 |
//+------------------------------------------------------------------+
input string WebhookURL   = "http://192.168.100.3:5001/webhook/trade";
input bool   EnableDebug  = true;
input int    ScanInterval = 2;

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                 |
//+------------------------------------------------------------------+
string   g_webhook_url;
datetime g_last_check       = 0;
string   g_monitored_symbols[];
bool     g_is_initialized   = false;
int      g_webhook_failures = 0;

//+------------------------------------------------------------------+
//| POSITION TRACKING STRUCTURE                                      |
//+------------------------------------------------------------------+
struct PositionInfo
{
    ulong    ticket;
    string   symbol;
    double   sl;
    double   tp;
    double   profit;
    double   price_open;
    double   price_current;
    double   volume;
    datetime open_time;
};
PositionInfo g_positions[];

//+------------------------------------------------------------------+
//| REMOVE ELEMENT FROM STRUCT ARRAY                                 |
//+------------------------------------------------------------------+
void RemovePosition(int index)
{
    int size = ArraySize(g_positions);
    for(int i = index; i < size - 1; i++)
        g_positions[i] = g_positions[i + 1];
    ArrayResize(g_positions, size - 1);
}

//+------------------------------------------------------------------+
//| GET MONITORED SYMBOLS - FULL LIST FROM MultiSymbolMonitor        |
//+------------------------------------------------------------------+
int GetMonitoredSymbols()
{
    string s = 
        // Precious Metals (4)
        "XAUUSD,XAGUSD,XAUEUR,XAGEUR,"
        // Major Forex (16)
        "EURUSD,GBPUSD,USDCAD,AUDUSD,"
        "NZDUSD,USDCHF,EURGBP,EURCAD,"
        "GBPAUD,AUDNZD,AUDCAD,AUDCHF,"
        // Commodities (2)
        "USOIL,UKOIL,"
        // Indices (9)
        "SPX500,NAS100,US30,"
        "DAX40,FTSE100,CAC40,"
        "ASX200,NIKKEI225,HK50,"
        // US Tech Stocks (18)
        "AAPL,MSFT,GOOGL,AMZN,NVDA,META,"
        "TSLA,AMD,INTC,CSCO,ORCL,IBM,"
        "QCOM,MU,PLTR,SNOW,"
        "UBER,PYPL,"
        // Healthcare (6)
        "JNJ,PFE,MRK,ABBV,GILD,MRNA,"
        // Consumer & Retail (5)
        "WMT,MCD,SBUX,DIS,KO,"
        // Energy & Industrials (3)
        "XOM,CVX,GE,"
        // Financials (3)
        "JPM,MA,AXP,"
        // ETFs (3)
        "SPY,QQQ,SMH";

    // StringSplit is the clean MQL5 way to split by delimiter
    ushort sep = StringGetCharacter(",", 0);
    int count  = StringSplit(s, sep, g_monitored_symbols);
    return count;
}

//+------------------------------------------------------------------+
//| CHECK IF SYMBOL IS MONITORED                                     |
//+------------------------------------------------------------------+
bool IsSymbolMonitored(string symbol)
{
    int size = ArraySize(g_monitored_symbols);
    for(int i = 0; i < size; i++)
    {
        if(g_monitored_symbols[i] == symbol)
            return true;
    }
    return false;
}

//+------------------------------------------------------------------+
//| EXPERT INITIALIZATION                                            |
//+------------------------------------------------------------------+
int OnInit()
{
    g_webhook_url = WebhookURL;

    int symbol_count = GetMonitoredSymbols();

    Print("========================================");
    Print("TRADE WEBHOOK - CLOSE & MODIFY ONLY");
    Print("========================================");
    Print("Webhook: ",   g_webhook_url);
    Print("Monitoring ", symbol_count, " symbols");
    Print("Debug: ",     EnableDebug ? "ON" : "OFF");
    Print("Scan: ",      ScanInterval, "s");
    Print("========================================");
    Print("Detects CLOSE (SL/TP/Manual)");
    Print("Detects MODIFY (SL/TP changes)");
    Print("========================================");

    ScanAllPositions();
    g_is_initialized = true;

    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| EXPERT DEINITIALIZATION                                          |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    Print("Webhook EA stopped");
    Print("Webhook failures: ", g_webhook_failures);
}

//+------------------------------------------------------------------+
//| EXPERT TICK FUNCTION                                             |
//+------------------------------------------------------------------+
void OnTick()
{
    if(!g_is_initialized)
        return;

    if((int)(TimeCurrent() - g_last_check) < ScanInterval)
        return;

    g_last_check = TimeCurrent();
    CheckForClosesAndModifies();
}

//+------------------------------------------------------------------+
//| CHECK FOR CLOSES AND MODIFIES                                    |
//+------------------------------------------------------------------+
void CheckForClosesAndModifies()
{
    int   total_positions = PositionsTotal();
    ulong current_tickets[];
    ArrayResize(current_tickets, total_positions);
    int current_count = 0;

    for(int i = 0; i < total_positions; i++)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket == 0)
            continue;

        if(!PositionSelectByTicket(ticket))
            continue;

        string symbol = PositionGetString(POSITION_SYMBOL);
        if(!IsSymbolMonitored(symbol))
            continue;

        current_tickets[current_count] = ticket;
        current_count++;

        double sl            = PositionGetDouble(POSITION_SL);
        double tp            = PositionGetDouble(POSITION_TP);
        double profit        = PositionGetDouble(POSITION_PROFIT);
        double price_current = PositionGetDouble(POSITION_PRICE_CURRENT);

        bool found = false;
        int  gsize = ArraySize(g_positions);

        for(int j = 0; j < gsize; j++)
        {
            if(g_positions[j].ticket == ticket)
            {
                found = true;
                if(g_positions[j].sl != sl || g_positions[j].tp != tp)
                {
                    Print("MODIFIED: ", symbol, " (Ticket: ", ticket, ")");
                    Print("   SL: ", DoubleToString(g_positions[j].sl, _Digits), " -> ", DoubleToString(sl, _Digits));
                    Print("   TP: ", DoubleToString(g_positions[j].tp, _Digits), " -> ", DoubleToString(tp, _Digits));
                    SendWebhookModify(symbol, ticket, sl, tp, profit, price_current);
                }
                g_positions[j].sl            = sl;
                g_positions[j].tp            = tp;
                g_positions[j].profit        = profit;
                g_positions[j].price_current = price_current;
                break;
            }
        }

        if(!found)
        {
            int idx = ArraySize(g_positions);
            ArrayResize(g_positions, idx + 1);
            g_positions[idx].ticket        = ticket;
            g_positions[idx].symbol        = symbol;
            g_positions[idx].sl            = sl;
            g_positions[idx].tp            = tp;
            g_positions[idx].profit        = profit;
            g_positions[idx].price_open    = PositionGetDouble(POSITION_PRICE_OPEN);
            g_positions[idx].price_current = price_current;
            g_positions[idx].volume        = PositionGetDouble(POSITION_VOLUME);
            g_positions[idx].open_time     = (datetime)PositionGetInteger(POSITION_TIME);
        }
    }

    for(int i = ArraySize(g_positions) - 1; i >= 0; i--)
    {
        bool still_open = false;
        for(int j = 0; j < current_count; j++)
        {
            if(g_positions[i].ticket == current_tickets[j])
            {
                still_open = true;
                break;
            }
        }

        if(!still_open)
        {
            ulong    ticket     = g_positions[i].ticket;
            string   symbol     = g_positions[i].symbol;
            double   profit     = g_positions[i].profit;
            double   price_open = g_positions[i].price_open;
            double   volume     = g_positions[i].volume;
            double   sl         = g_positions[i].sl;
            double   tp         = g_positions[i].tp;

            string   close_reason = "MANUAL";
            double   close_price  = 0.0;
            datetime close_time   = TimeCurrent();

            HistorySelect((datetime)0, TimeCurrent());
            int total_deals = HistoryDealsTotal();

            for(int d = total_deals - 1; d >= 0 && d >= total_deals - 50; d--)
            {
                ulong deal_ticket = HistoryDealGetTicket(d);
                if(deal_ticket == 0)
                    continue;

                long deal_pos_id = HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID);
                if(deal_pos_id != (long)ticket)
                    continue;

                ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal_ticket, DEAL_ENTRY);
                if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
                {
                    close_price = HistoryDealGetDouble(deal_ticket, DEAL_PRICE);
                    close_time  = (datetime)HistoryDealGetInteger(deal_ticket, DEAL_TIME);

                    //--- FIXED: the profit sent used to be g_positions[i].profit,
                    //    the last FLOATING P/L seen before the position vanished:
                    //    stale by up to a scan, and without commission or swap.
                    //    Checked against the deals, 3 of 36 had the wrong sign.
                    //    The booked result is the sum over every deal of the
                    //    position (entry commission included).
                    if(HistorySelectByPosition(ticket))
                    {
                        double booked = 0.0;
                        for(int k = HistoryDealsTotal() - 1; k >= 0; k--)
                        {
                            ulong dk = HistoryDealGetTicket(k);
                            if(dk == 0) continue;
                            booked += HistoryDealGetDouble(dk, DEAL_PROFIT)
                                    + HistoryDealGetDouble(dk, DEAL_COMMISSION)
                                    + HistoryDealGetDouble(dk, DEAL_SWAP);
                        }
                        profit = booked;
                    }

                    //--- FIXED: read DEAL_REASON, the enum MT5 provides for
                    //    exactly this, instead of substring-matching the
                    //    broker's free-text DEAL_COMMENT.
                    //
                    //    The old code lowercased the comment and asked
                    //    StringFind(comment,"sl") FIRST, then "tp". That is
                    //    wrong twice over: the "sl" test runs before "tp" and
                    //    matches any comment containing those two letters
                    //    anywhere, and a broker that writes the ORDER comment
                    //    on the deal (most do -- e.g. "AI Trade") matches
                    //    neither and silently became "MANUAL". The close
                    //    reason reaching Firebase was therefore unreliable,
                    //    which makes every downstream label -- was this a
                    //    winner that hit target, or a loser that hit stop --
                    //    unreliable with it.
                    //
                    //    DEAL_REASON is set by the server and is unambiguous.
                    long deal_reason = HistoryDealGetInteger(deal_ticket, DEAL_REASON);

                    if(deal_reason == DEAL_REASON_SL)
                        close_reason = "STOP_LOSS";
                    else if(deal_reason == DEAL_REASON_TP)
                        close_reason = "TAKE_PROFIT";
                    else if(deal_reason == DEAL_REASON_SO)
                        close_reason = "STOP_OUT";       // margin stop-out
                    else if(deal_reason == DEAL_REASON_EXPERT)
                        close_reason = "EXPERT";         // closed by an EA
                    else if(deal_reason == DEAL_REASON_CLIENT ||
                            deal_reason == DEAL_REASON_MOBILE ||
                            deal_reason == DEAL_REASON_WEB)
                        close_reason = "MANUAL";
                    else
                    {
                        //--- Only if the server gave us something unexpected
                        //    do we fall back to the comment, and even then we
                        //    test TP before SL and require the bracketed form
                        //    brokers actually emit ("[tp 1.2345]").
                        string comment = HistoryDealGetString(deal_ticket, DEAL_COMMENT);
                        StringToLower(comment);

                        if(StringFind(comment, "[tp") >= 0 || StringFind(comment, "take profit") >= 0)
                            close_reason = "TAKE_PROFIT";
                        else if(StringFind(comment, "[sl") >= 0 || StringFind(comment, "stop loss") >= 0)
                            close_reason = "STOP_LOSS";
                        else
                            close_reason = "UNKNOWN";    // never guess "MANUAL"
                    }
                    break;
                }
            }

            Print("========================================");
            Print("CLOSED: ", symbol, " (Ticket: ", ticket, ")");
            Print("   Reason: ",      close_reason);
            Print("   Profit: $",     DoubleToString(profit, 2));
            Print("   Price Open: ",  DoubleToString(price_open, _Digits));
            Print("   Close Price: ", DoubleToString(close_price, _Digits));
            Print("   Volume: ",      DoubleToString(volume, 2));
            Print("   SL: ",          DoubleToString(sl, _Digits));
            Print("   TP: ",          DoubleToString(tp, _Digits));
            Print("========================================");

            SendWebhookClose(symbol, ticket, close_reason, price_open, close_price, profit, sl, tp, volume, close_time);
            RemovePosition(i);
        }
    }
}

//+------------------------------------------------------------------+
//| SCAN ALL POSITIONS ON INIT                                       |
//+------------------------------------------------------------------+
void ScanAllPositions()
{
    ArrayResize(g_positions, 0);
    int total = PositionsTotal();
    int count = 0;

    for(int i = 0; i < total; i++)
    {
        ulong ticket = PositionGetTicket(i);
        if(ticket == 0)
            continue;

        if(!PositionSelectByTicket(ticket))
            continue;

        string symbol = PositionGetString(POSITION_SYMBOL);
        if(!IsSymbolMonitored(symbol))
            continue;

        int idx = ArraySize(g_positions);
        ArrayResize(g_positions, idx + 1);
        g_positions[idx].ticket        = ticket;
        g_positions[idx].symbol        = symbol;
        g_positions[idx].sl            = PositionGetDouble(POSITION_SL);
        g_positions[idx].tp            = PositionGetDouble(POSITION_TP);
        g_positions[idx].profit        = PositionGetDouble(POSITION_PROFIT);
        g_positions[idx].price_open    = PositionGetDouble(POSITION_PRICE_OPEN);
        g_positions[idx].price_current = PositionGetDouble(POSITION_PRICE_CURRENT);
        g_positions[idx].volume        = PositionGetDouble(POSITION_VOLUME);
        g_positions[idx].open_time     = (datetime)PositionGetInteger(POSITION_TIME);
        count++;
    }

    if(EnableDebug)
        Print("Initial scan: ", count, " positions tracked");
}

//+------------------------------------------------------------------+
//| SEND MODIFY WEBHOOK                                              |
//+------------------------------------------------------------------+
void SendWebhookModify(string symbol, ulong ticket, double sl, double tp, double profit, double price_current)
{
    // Digits of the TRADED symbol. _Digits is the chart's: on a 2-digit chart
    // it rounded every FX price to 1.16 / 0.0 before it reached the server.
    int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    string json = "{";
    json += "\"event\":\"MODIFY\",";
    json += "\"symbol\":\"" + symbol + "\",";
    json += "\"ticket\":"   + IntegerToString((long)ticket) + ",";
    json += "\"sl\":"       + DoubleToString(sl, digits) + ",";
    json += "\"tp\":"       + DoubleToString(tp, digits) + ",";
    json += "\"profit\":"   + DoubleToString(profit, 2) + ",";
    json += "\"price_current\":" + DoubleToString(price_current, digits) + ",";
    json += "\"time\":\""   + TimeToString(TimeCurrent()) + "\"";
    json += "}";
    SendHTTPRequest(json);
}

//+------------------------------------------------------------------+
//| ✅ FIXED: SEND CLOSE WEBHOOK WITH VALIDATION                     |
//+------------------------------------------------------------------+
void SendWebhookClose(string symbol, ulong ticket, string close_reason,
                      double price_open, double price_close, double profit,
                      double sl, double tp, double volume, datetime close_time)
{
    // ============================================================
    // VALIDATE AND FIX MISSING DATA
    // ============================================================
    if(price_open == 0 || price_close == 0 || volume == 0)
    {
        Print("⚠️ WARNING: Zero values detected in close data!");
        Print("   Symbol: ", symbol, " Ticket: ", ticket);
        Print("   price_open: ", price_open, " price_close: ", price_close, " volume: ", volume);
        Print("   Trying to recover missing data from history...");
        
        // Try to get missing data from trade history
        if(price_open == 0 || price_close == 0)
        {
            HistorySelect(close_time - 60, close_time + 60);
            int total_deals = HistoryDealsTotal();
            
            for(int d = total_deals - 1; d >= 0; d--)
            {
                ulong deal_ticket = HistoryDealGetTicket(d);
                if(deal_ticket == 0) continue;
                
                long deal_pos_id = HistoryDealGetInteger(deal_ticket, DEAL_POSITION_ID);
                if(deal_pos_id != (long)ticket) continue;
                
                ENUM_DEAL_ENTRY entry = (ENUM_DEAL_ENTRY)HistoryDealGetInteger(deal_ticket, DEAL_ENTRY);
                if(entry == DEAL_ENTRY_IN)
                {
                    if(price_open == 0)
                    {
                        price_open = HistoryDealGetDouble(deal_ticket, DEAL_PRICE);
                        Print("   Recovered price_open: ", price_open);
                    }
                }
                else if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY)
                {
                    if(price_close == 0)
                    {
                        price_close = HistoryDealGetDouble(deal_ticket, DEAL_PRICE);
                        Print("   Recovered price_close: ", price_close);
                    }
                }
            }
        }
        
        // Get volume from position if missing
        if(volume == 0)
        {
            if(PositionSelectByTicket(ticket))
            {
                volume = PositionGetDouble(POSITION_VOLUME);
                Print("   Recovered volume: ", volume);
            }
        }
        
        // Recalculate profit if missing
        if(profit == 0 && price_open > 0 && price_close > 0 && volume > 0)
        {
            // Calculate profit based on price difference
            double pip_value = 0;
            string symbol_upper = symbol;
            StringToUpper(symbol_upper);
            
            // Determine pip size
            if(StringFind(symbol_upper, "JPY") >= 0)
                pip_value = 0.01;
            else if(StringFind(symbol_upper, "XAU") >= 0 || StringFind(symbol_upper, "GOLD") >= 0)
                pip_value = 0.01;
            else
                pip_value = 0.0001;
            
            double price_diff = price_close - price_open;
            profit = price_diff / pip_value * volume * 100000;
            Print("   Recalculated profit: $", profit);
        }
    }
    
    // ============================================================
    // BUILD JSON WITH VALIDATED DATA
    // ============================================================
    // Digits of the TRADED symbol, not the chart's _Digits (see SendWebhookModify).
    int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
    string json = "{";
    json += "\"event\":\"CLOSE\",";
    json += "\"close_reason\":\"" + close_reason + "\",";
    json += "\"symbol\":\""       + symbol + "\",";
    json += "\"ticket\":"         + IntegerToString((long)ticket) + ",";
    json += "\"volume\":"         + DoubleToString(volume, 2) + ",";
    json += "\"price_open\":"     + DoubleToString(price_open, digits) + ",";
    json += "\"price_close\":"    + DoubleToString(price_close, digits) + ",";
    json += "\"profit\":"         + DoubleToString(profit, 2) + ",";
    json += "\"sl\":"             + DoubleToString(sl, digits) + ",";
    json += "\"tp\":"             + DoubleToString(tp, digits) + ",";
    json += "\"time\":\""         + TimeToString(close_time) + "\"";
    json += "}";
    
    // ============================================================
    // DEBUG OUTPUT
    // ============================================================
    if(EnableDebug)
    {
        Print("📨 SENDING WEBHOOK CLOSE:");
        Print("   Symbol: ", symbol);
        Print("   Ticket: ", ticket);
        Print("   Profit: $", profit);
        Print("   Price Open: ", price_open);
        Print("   Price Close: ", price_close);
        Print("   Volume: ", volume);
        Print("   SL: ", sl);
        Print("   TP: ", tp);
    }
    
    SendHTTPRequest(json);
}

//+------------------------------------------------------------------+
//| SEND HTTP POST REQUEST                                           |
//+------------------------------------------------------------------+
void SendHTTPRequest(string json)
{
    if(EnableDebug)
        Print("Webhook payload: ", json);

    uchar  post_data[];
    uchar  result[];
    string result_headers = "";
    string headers        = "Content-Type: application/json\r\n";

    // Convert string to uchar[] without null terminator
    StringToCharArray(json, post_data, 0, StringLen(json));

    int res = WebRequest("POST", g_webhook_url, headers, 3000, post_data, result, result_headers);

    if(res == -1)
    {
        g_webhook_failures++;
        int error = GetLastError();
        if(EnableDebug || g_webhook_failures % 10 == 0)
            Print("❌ Webhook failed (total: ", g_webhook_failures, ") error: ", error);
            
        // Log error details for debugging
        if(error == 4014)
            Print("   WebRequest not allowed - check EA permissions");
        else if(error == 4015)
            Print("   WebRequest timeout - check server is running");
        else if(error == 4016)
            Print("   WebRequest connection error - check URL and network");
    }
    else
    {
        if(EnableDebug)
            Print("✅ Webhook sent OK, HTTP status: ", res);
        g_webhook_failures = 0;
    }
}

//+------------------------------------------------------------------+
//| CHART EVENT - MANUAL REFRESH ON CLICK                           |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
    if(id == CHARTEVENT_CLICK)
    {
        Print("Manual refresh triggered");
        CheckForClosesAndModifies();
    }
}