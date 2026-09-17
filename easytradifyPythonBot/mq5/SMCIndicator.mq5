//+------------------------------------------------------------------+
//|                                                 SMCIndicator.mq5 |
//|                                    Copyright 2026, AI Trading    |
//|          Smart Money Concepts (SMC) Chart Visualization Indicator |
//+------------------------------------------------------------------+
#property copyright "AI Trading System"
#property version   "1.00"
#property description "SMC Indicator - Draws BOS/CHoCH, Order Blocks, FVG, Liquidity Sweeps, Premium/Discount"
#property indicator_chart_window
#property indicator_plots 0

//+------------------------------------------------------------------+
//| INPUT PARAMETERS                                                 |
//+------------------------------------------------------------------+
input string   DataFileName    = "smc_data.json";   // JSON data file name (in MQL5/Files or Common)
input bool     UseCommonFolder = true;               // Use Terminal\Common\Files folder
input int      RefreshSeconds  = 5;                  // Refresh interval (seconds)
input bool     ShowOrderBlocks = true;               // Show Order Blocks
input bool     ShowFVG         = true;               // Show Fair Value Gaps
input bool     ShowLiquidity   = true;               // Show Liquidity Sweeps
input bool     ShowStructure   = true;               // Show BOS/CHoCH Structure
input bool     ShowPremiumDisc = true;               // Show Premium/Discount Zones
input bool     ShowSwingPoints = true;               // Show Swing Points
input bool     EnableDebug     = false;              // Debug logging

// Colors
input color    BullishOBColor  = clrLimeGreen;       // Bullish Order Block color
input color    BearishOBColor  = clrCrimson;         // Bearish Order Block color
input color    FVGBullishColor = clrDodgerBlue;      // Bullish FVG color
input color    FVGBearishColor = clrOrange;          // Bearish FVG color
input color    BOSColor        = clrAqua;            // BOS line color
input color    CHoCHColor      = clrMagenta;         // CHoCH line color
input color    SweepBullColor  = clrLime;            // Bullish sweep color
input color    SweepBearColor  = clrRed;             // Bearish sweep color
input color    PremiumColor    = clrMaroon;          // Premium zone color
input color    DiscountColor   = clrDarkGreen;       // Discount zone color
input color    EquilibriumColor= clrDimGray;         // Equilibrium zone color
input color    SwingHighColor  = clrRed;             // Swing high color
input color    SwingLowColor   = clrLime;            // Swing low color

//+------------------------------------------------------------------+
//| GLOBAL VARIABLES                                                 |
//+------------------------------------------------------------------+
string   g_prefix = "SMC_";
datetime g_last_refresh = 0;
string   g_last_json = "";
int      g_update_counter = 0;

// SMC Data Structure
struct SMCData
{
    string   symbol;
    string   timeframe;
    double   current_price;
    datetime update_time;

    // Market Structure
    string   ms_structure;
    string   ms_last_event;
    double   ms_swing_high;
    double   ms_swing_low;
    int      ms_swing_count;

    // Order Blocks
    bool     ob_has_bullish;
    double   ob_bull_high;
    double   ob_bull_low;
    int      ob_bull_bars_ago;
    bool     ob_has_bearish;
    double   ob_bear_high;
    double   ob_bear_low;
    int      ob_bear_bars_ago;
    bool     price_in_bull_ob;
    bool     price_in_bear_ob;

    // FVG
    bool     fvg_has;
    string   fvg_type;
    double   fvg_high;
    double   fvg_low;
    double   fvg_level;
    string   fvg_tier;
    double   fvg_tier_score;
    bool     fvg_valid;

    // Liquidity Sweep
    bool     ls_swept;
    string   ls_type;
    double   ls_level;

    // Premium/Discount
    string   pd_zone;
    double   pd_range_high;
    double   pd_range_low;
    double   pd_position_pct;
    bool     pd_in_ote_discount;
    bool     pd_in_ote_premium;

    // Recommendation
    string   recommendation;
    double   confluence_score;
    int      confluence_count;
};

SMCData g_smc;

//+------------------------------------------------------------------+
//| INITIALIZATION                                                   |
//+------------------------------------------------------------------+
int OnInit()
{
    g_prefix = "SMC_" + _Symbol + "_";

    Print("========================================");
    Print("SMC INDICATOR - Smart Money Concepts");
    Print("========================================");
    Print("Symbol: ", _Symbol);
    Print("Data File: ", DataFileName);
    Print("Common Folder: ", UseCommonFolder ? "YES" : "NO");
    Print("Refresh: ", RefreshSeconds, "s");
    Print("========================================");

    // Initialize SMC data
    ResetSMCData();

    // Try initial load
    LoadAndDrawSMC();

    EventSetTimer(RefreshSeconds);
    return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| DEINITIALIZATION                                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
    EventKillTimer();
    RemoveAllObjects();
    Print("SMC Indicator stopped");
}

//+------------------------------------------------------------------+
//| TIMER FUNCTION - PERIODIC REFRESH                                |
//+------------------------------------------------------------------+
void OnTimer()
{
    LoadAndDrawSMC();
}

//+------------------------------------------------------------------+
//| CHART EVENT - REFRESH ON CLICK                                   |
//+------------------------------------------------------------------+
void OnChartEvent(const int id, const long &lparam, const double &dparam, const string &sparam)
{
    if(id == CHARTEVENT_CLICK)
    {
        if(EnableDebug) Print("Manual SMC refresh triggered");
        LoadAndDrawSMC();
        ChartRedraw();
    }
}

//+------------------------------------------------------------------+
//| RESET SMC DATA TO DEFAULTS                                       |
//+------------------------------------------------------------------+
void ResetSMCData()
{
    g_smc.symbol = _Symbol;
    g_smc.timeframe = "";
    g_smc.current_price = 0;
    g_smc.update_time = 0;

    g_smc.ms_structure = "UNKNOWN";
    g_smc.ms_last_event = "";
    g_smc.ms_swing_high = 0;
    g_smc.ms_swing_low = 0;
    g_smc.ms_swing_count = 0;

    g_smc.ob_has_bullish = false;
    g_smc.ob_bull_high = 0;
    g_smc.ob_bull_low = 0;
    g_smc.ob_bull_bars_ago = 0;
    g_smc.ob_has_bearish = false;
    g_smc.ob_bear_high = 0;
    g_smc.ob_bear_low = 0;
    g_smc.ob_bear_bars_ago = 0;
    g_smc.price_in_bull_ob = false;
    g_smc.price_in_bear_ob = false;

    g_smc.fvg_has = false;
    g_smc.fvg_type = "";
    g_smc.fvg_high = 0;
    g_smc.fvg_low = 0;
    g_smc.fvg_level = 0;
    g_smc.fvg_tier = "";
    g_smc.fvg_tier_score = 0;
    g_smc.fvg_valid = false;

    g_smc.ls_swept = false;
    g_smc.ls_type = "";
    g_smc.ls_level = 0;

    g_smc.pd_zone = "UNKNOWN";
    g_smc.pd_range_high = 0;
    g_smc.pd_range_low = 0;
    g_smc.pd_position_pct = 50.0;
    g_smc.pd_in_ote_discount = false;
    g_smc.pd_in_ote_premium = false;

    g_smc.recommendation = "NEUTRAL";
    g_smc.confluence_score = 0;
    g_smc.confluence_count = 0;
}

//+------------------------------------------------------------------+
//| LOAD JSON AND DRAW SMC ELEMENTS                                  |
//+------------------------------------------------------------------+
void LoadAndDrawSMC()
{
    string json = ReadJSONFile();
    if(json == "")
    {
        if(EnableDebug && g_update_counter % 12 == 0)
            Print("SMC: No data file found or empty");
        g_update_counter++;
        return;
    }

    if(json == g_last_json)
    {
        if(EnableDebug) Print("SMC: Data unchanged, skipping redraw");
        g_update_counter++;
        return;
    }

    g_last_json = json;
    g_update_counter++;

    // Parse JSON
    ResetSMCData();
    if(!ParseSMCJSON(json))
    {
        if(EnableDebug) Print("SMC: Failed to parse JSON");
        return;
    }

    // Remove old objects and draw new ones
    RemoveAllObjects();
    DrawAllSMCElements();

    if(EnableDebug)
    {
        Print("SMC: Drew elements - Structure: ", g_smc.ms_structure,
              " | Rec: ", g_smc.recommendation,
              " | Score: ", g_smc.confluence_score);
    }
}

//+------------------------------------------------------------------+
//| READ JSON FILE                                                   |
//+------------------------------------------------------------------+
string ReadJSONFile()
{
    int flags = FILE_READ | FILE_TXT | FILE_ANSI;
    if(UseCommonFolder) flags |= FILE_COMMON;

    int handle = FileOpen(DataFileName, flags);
    if(handle == INVALID_HANDLE)
    {
        if(EnableDebug && g_update_counter % 12 == 0)
        {
            int err = GetLastError();
            Print("SMC: Cannot open file '", DataFileName, "' error: ", err);
        }
        return "";
    }

    string content = "";
    while(!FileIsEnding(handle))
    {
        string line = FileReadString(handle);
        content += line;
    }
    FileClose(handle);

    return content;
}

//+------------------------------------------------------------------+
//| JSON HELPER: FIND VALUE FOR KEY                                  |
//| Returns the value string after "key":                            |
//+------------------------------------------------------------------+
string JSONGetString(string json, string key)
{
    string search = "\"" + key + "\"";
    int pos = StringFind(json, search, 0);
    if(pos < 0) return "";

    // Find the colon after the key
    int colonPos = StringFind(json, ":", pos);
    if(colonPos < 0) return "";

    int start = colonPos + 1;
    // Skip whitespace
    while(start < StringLen(json) && (StringGetCharacter(json, start) == ' ' ||
                                       StringGetCharacter(json, start) == '\t' ||
                                       StringGetCharacter(json, start) == '\n' ||
                                       StringGetCharacter(json, start) == '\r'))
        start++;

    if(start >= StringLen(json)) return "";

    int firstChar = StringGetCharacter(json, start);

    // If it starts with a quote, extract the string
    if(firstChar == '"')
    {
        int endQuote = StringFind(json, "\"", start + 1);
        if(endQuote < 0) return "";
        return StringSubstr(json, start + 1, endQuote - start - 1);
    }

    // If it starts with { or [, find the matching close bracket
    if(firstChar == '{' || firstChar == '[')
    {
        int openChar = firstChar;
        int closeChar = (openChar == '{') ? '}' : ']';
        int depth = 1;
        int i = start + 1;
        while(i < StringLen(json) && depth > 0)
        {
            int ch = StringGetCharacter(json, i);
            if(ch == openChar) depth++;
            else if(ch == closeChar) depth--;
            if(depth == 0) break;
            i++;
        }
        return StringSubstr(json, start, i - start + 1);
    }

    // Otherwise, it's a number/bool/null - read until comma or close bracket
    int i = start;
    while(i < StringLen(json))
    {
        int ch = StringGetCharacter(json, i);
        if(ch == ',' || ch == '}' || ch == ']' || ch == '\n' || ch == '\r')
            break;
        i++;
    }
    string val = StringSubstr(json, start, i - start);
    StringTrimLeft(val);
    StringTrimRight(val);
    return val;
}

//+------------------------------------------------------------------+
//| JSON HELPER: GET NUMERIC VALUE                                   |
//+------------------------------------------------------------------+
double JSONGetDouble(string json, string key)
{
    string val = JSONGetString(json, key);
    if(val == "" || val == "null") return 0.0;
    return StringToDouble(val);
}

//+------------------------------------------------------------------+
//| JSON HELPER: GET INTEGER VALUE                                   |
//+------------------------------------------------------------------+
int JSONGetInt(string json, string key)
{
    string val = JSONGetString(json, key);
    if(val == "" || val == "null") return 0;
    return (int)StringToInteger(val);
}

//+------------------------------------------------------------------+
//| JSON HELPER: GET BOOLEAN VALUE                                   |
//+------------------------------------------------------------------+
bool JSONGetBool(string json, string key)
{
    string val = JSONGetString(json, key);
    return (val == "true");
}

//+------------------------------------------------------------------+
//| JSON HELPER: GET VALUE FROM NESTED OBJECT                        |
//| Searches within a sub-JSON string for a key                      |
//+------------------------------------------------------------------+
string JSONGetNestedString(string subJson, string key)
{
    return JSONGetString(subJson, key);
}

double JSONGetNestedDouble(string subJson, string key)
{
    return JSONGetDouble(subJson, key);
}

int JSONGetNestedInt(string subJson, string key)
{
    return JSONGetInt(subJson, key);
}

bool JSONGetNestedBool(string subJson, string key)
{
    return JSONGetBool(subJson, key);
}

//+------------------------------------------------------------------+
//| PARSE SMC JSON DATA                                              |
//+------------------------------------------------------------------+
bool ParseSMCJSON(string json)
{
    // Check if data is for this symbol
    string symbol = JSONGetString(json, "symbol");
    if(symbol != "" && symbol != _Symbol)
    {
        if(EnableDebug) Print("SMC: Data is for '", symbol, "' but chart is '", _Symbol, "'");
        // Still try to use it - some symbols may have different naming
    }

    g_smc.symbol = (symbol != "") ? symbol : _Symbol;
    g_smc.timeframe = JSONGetString(json, "timeframe");
    g_smc.current_price = JSONGetDouble(json, "current_price");
    g_smc.update_time = (datetime)JSONGetInt(json, "update_time");

    // Parse market_structure sub-object
    string msJson = JSONGetString(json, "market_structure");
    if(msJson != "")
    {
        g_smc.ms_structure = JSONGetNestedString(msJson, "structure");
        if(g_smc.ms_structure == "") g_smc.ms_structure = "UNKNOWN";
        g_smc.ms_last_event = JSONGetNestedString(msJson, "last_event");
        if(g_smc.ms_last_event == "null") g_smc.ms_last_event = "";
        g_smc.ms_swing_high = JSONGetNestedDouble(msJson, "last_swing_high");
        g_smc.ms_swing_low = JSONGetNestedDouble(msJson, "last_swing_low");
        g_smc.ms_swing_count = JSONGetNestedInt(msJson, "swing_count");
    }

    // Parse order_blocks sub-object
    string obJson = JSONGetString(json, "order_blocks");
    if(obJson != "")
    {
        string bullOB = JSONGetNestedString(obJson, "bullish_ob");
        if(bullOB != "" && bullOB != "null")
        {
            g_smc.ob_has_bullish = true;
            g_smc.ob_bull_high = JSONGetNestedDouble(bullOB, "high");
            g_smc.ob_bull_low = JSONGetNestedDouble(bullOB, "low");
            g_smc.ob_bull_bars_ago = JSONGetNestedInt(bullOB, "bars_ago");
        }

        string bearOB = JSONGetNestedString(obJson, "bearish_ob");
        if(bearOB != "" && bearOB != "null")
        {
            g_smc.ob_has_bearish = true;
            g_smc.ob_bear_high = JSONGetNestedDouble(bearOB, "high");
            g_smc.ob_bear_low = JSONGetNestedDouble(bearOB, "low");
            g_smc.ob_bear_bars_ago = JSONGetNestedInt(bearOB, "bars_ago");
        }

        g_smc.price_in_bull_ob = JSONGetNestedBool(obJson, "price_in_bullish_ob");
        g_smc.price_in_bear_ob = JSONGetNestedBool(obJson, "price_in_bearish_ob");
    }

    // Parse fvg sub-object
    string fvgJson = JSONGetString(json, "fvg");
    if(fvgJson != "")
    {
        g_smc.fvg_type = JSONGetNestedString(fvgJson, "type");
        if(g_smc.fvg_type != "" && g_smc.fvg_type != "null" && g_smc.fvg_type != "NONE")
        {
            g_smc.fvg_has = true;
            g_smc.fvg_high = JSONGetNestedDouble(fvgJson, "high");
            g_smc.fvg_low = JSONGetNestedDouble(fvgJson, "low");
            g_smc.fvg_level = JSONGetNestedDouble(fvgJson, "level");
            g_smc.fvg_tier = JSONGetNestedString(fvgJson, "tier");
            g_smc.fvg_tier_score = JSONGetNestedDouble(fvgJson, "tier_score");
            g_smc.fvg_valid = JSONGetNestedBool(fvgJson, "valid");
        }
    }

    // Parse liquidity_sweep sub-object
    string lsJson = JSONGetString(json, "liquidity_sweep");
    if(lsJson != "")
    {
        g_smc.ls_swept = JSONGetNestedBool(lsJson, "swept");
        g_smc.ls_type = JSONGetNestedString(lsJson, "type");
        if(g_smc.ls_type == "null") g_smc.ls_type = "";
        g_smc.ls_level = JSONGetNestedDouble(lsJson, "level");
    }

    // Parse premium_discount sub-object
    string pdJson = JSONGetString(json, "premium_discount");
    if(pdJson != "")
    {
        g_smc.pd_zone = JSONGetNestedString(pdJson, "zone");
        if(g_smc.pd_zone == "") g_smc.pd_zone = "UNKNOWN";
        g_smc.pd_range_high = JSONGetNestedDouble(pdJson, "range_high");
        g_smc.pd_range_low = JSONGetNestedDouble(pdJson, "range_low");
        g_smc.pd_position_pct = JSONGetNestedDouble(pdJson, "position_pct");
        g_smc.pd_in_ote_discount = JSONGetNestedBool(pdJson, "in_ote_discount");
        g_smc.pd_in_ote_premium = JSONGetNestedBool(pdJson, "in_ote_premium");
    }

    // Parse recommendation
    g_smc.recommendation = JSONGetString(json, "recommendation");
    if(g_smc.recommendation == "") g_smc.recommendation = "NEUTRAL";
    g_smc.confluence_score = JSONGetDouble(json, "confluence_score");
    g_smc.confluence_count = JSONGetInt(json, "confluence_count");

    return true;
}

//+------------------------------------------------------------------+
//| DRAW ALL SMC ELEMENTS ON CHART                                   |
//+------------------------------------------------------------------+
void DrawAllSMCElements()
{
    datetime now = TimeCurrent();
    datetime endTime = now + PeriodSeconds() * 50; // Extend into future

    // 1. Draw Premium/Discount zones (drawn first as background)
    if(ShowPremiumDisc)
        DrawPremiumDiscountZones(endTime);

    // 2. Draw Order Blocks
    if(ShowOrderBlocks)
    {
        if(g_smc.ob_has_bullish)
            DrawOrderBlock(true, g_smc.ob_bull_high, g_smc.ob_bull_low, g_smc.ob_bull_bars_ago, endTime);
        if(g_smc.ob_has_bearish)
            DrawOrderBlock(false, g_smc.ob_bear_high, g_smc.ob_bear_low, g_smc.ob_bear_bars_ago, endTime);
    }

    // 3. Draw FVG
    if(ShowFVG && g_smc.fvg_has && g_smc.fvg_valid)
        DrawFVG(endTime);

    // 4. Draw Liquidity Sweep
    if(ShowLiquidity && g_smc.ls_swept)
        DrawLiquiditySweep(endTime);

    // 5. Draw Market Structure (BOS/CHoCH)
    if(ShowStructure)
        DrawMarketStructure(endTime);

    // 6. Draw Swing Points
    if(ShowSwingPoints)
        DrawSwingPoints(endTime);

    // 7. Draw Info Label
    DrawInfoLabel(endTime);
}

//+------------------------------------------------------------------+
//| DRAW PREMIUM/DISCOUNT ZONES                                      |
//+------------------------------------------------------------------+
void DrawPremiumDiscountZones(datetime endTime)
{
    if(g_smc.pd_range_high <= 0 || g_smc.pd_range_low <= 0)
        return;

    double range = g_smc.pd_range_high - g_smc.pd_range_low;
    if(range <= 0) return;

    datetime startTime = GetStartTime(100);

    // Equilibrium zone (30%-70%)
    double eqHigh = g_smc.pd_range_low + range * 0.70;
    double eqLow = g_smc.pd_range_low + range * 0.30;

    string eqName = g_prefix + "PD_EQUILIBRIUM";
    CreateRectangle(eqName, startTime, eqLow, endTime, eqHigh, EquilibriumColor, false, clrNONE, 1, STYLE_SOLID, 50);
    AddLabel(eqName, "EQUILIBRIUM", startTime, eqHigh, EquilibriumColor, 8);

    // Premium zone (70%-100%)
    double premHigh = g_smc.pd_range_high;
    double premLow = g_smc.pd_range_low + range * 0.70;

    string premName = g_prefix + "PD_PREMIUM";
    CreateRectangle(premName, startTime, premLow, endTime, premHigh, PremiumColor, false, clrNONE, 1, STYLE_SOLID, 40);
    AddLabel(premName, "PREMIUM", startTime, premHigh, PremiumColor, 8);

    // Discount zone (0%-30%)
    double discHigh = g_smc.pd_range_low + range * 0.30;
    double discLow = g_smc.pd_range_low;

    string discName = g_prefix + "PD_DISCOUNT";
    CreateRectangle(discName, startTime, discLow, endTime, discHigh, DiscountColor, false, clrNONE, 1, STYLE_SOLID, 40);
    AddLabel(discName, "DISCOUNT", startTime, discHigh, DiscountColor, 8);

    // Draw range boundaries
    string rhName = g_prefix + "PD_RANGE_HIGH";
    CreateHLine(rhName, g_smc.pd_range_high, clrSilver, STYLE_DASH, 1);
    AddLabel(rhName + "_lbl", "Range High", startTime, g_smc.pd_range_high, clrSilver, 7);

    string rlName = g_prefix + "PD_RANGE_LOW";
    CreateHLine(rlName, g_smc.pd_range_low, clrSilver, STYLE_DASH, 1);
    AddLabel(rlName + "_lbl", "Range Low", startTime, g_smc.pd_range_low, clrSilver, 7);

    // Draw OTE zones if applicable
    if(g_smc.pd_in_ote_discount)
    {
        double oteHigh = g_smc.pd_range_low + range * 0.382;
        double oteLow = g_smc.pd_range_low + range * 0.21;
        string oteName = g_prefix + "PD_OTE_DISCOUNT";
        CreateRectangle(oteName, startTime, oteLow, endTime, oteHigh, clrGold, false, clrGold, 1, STYLE_DOT, 60);
        AddLabel(oteName, "OTE Discount", startTime, oteHigh, clrGold, 7);
    }

    if(g_smc.pd_in_ote_premium)
    {
        double oteHigh = g_smc.pd_range_low + range * 0.79;
        double oteLow = g_smc.pd_range_low + range * 0.618;
        string oteName = g_prefix + "PD_OTE_PREMIUM";
        CreateRectangle(oteName, startTime, oteLow, endTime, oteHigh, clrGold, false, clrGold, 1, STYLE_DOT, 60);
        AddLabel(oteName, "OTE Premium", startTime, oteHigh, clrGold, 7);
    }

    // Draw current position line
    if(g_smc.current_price > 0)
    {
        string posName = g_prefix + "PD_POSITION";
        CreateHLine(posName, g_smc.current_price, clrYellow, STYLE_DASHDOT, 1);
    }
}

//+------------------------------------------------------------------+
//| DRAW ORDER BLOCK                                                 |
//+------------------------------------------------------------------+
void DrawOrderBlock(bool isBullish, double obHigh, double obLow, int barsAgo, datetime endTime)
{
    color clr = isBullish ? BullishOBColor : BearishOBColor;
    string typeName = isBullish ? "Bullish" : "Bearish";
    string name = g_prefix + "OB_" + typeName;

    // Estimate start time based on bars ago
    datetime startTime = GetStartTime(barsAgo + 5);

    // Draw the order block rectangle
    CreateRectangle(name, startTime, obLow, endTime, obHigh, clr, true, clr, 1, STYLE_SOLID, 20);

    // Add label
    string label = typeName + " OB";
    if(isBullish && g_smc.price_in_bull_ob)
        label += " ★ (Price Here)";
    else if(!isBullish && g_smc.price_in_bear_ob)
        label += " ★ (Price Here)";

    AddLabel(name + "_lbl", label, startTime, obHigh, clr, 9);
}

//+------------------------------------------------------------------+
//| DRAW FAIR VALUE GAP                                              |
//+------------------------------------------------------------------+
void DrawFVG(datetime endTime)
{
    color clr = (g_smc.fvg_type == "BULLISH") ? FVGBullishColor : FVGBearishColor;
    string name = g_prefix + "FVG";

    datetime startTime = GetStartTime(30);

    // Draw FVG rectangle
    CreateRectangle(name, startTime, g_smc.fvg_low, endTime, g_smc.fvg_high, clr, true, clr, 1, STYLE_SOLID, 30);

    // Draw FVG level line
    string lineName = name + "_level";
    CreateHLine(lineName, g_smc.fvg_level, clr, STYLE_DASH, 1);

    // Add label
    string label = "FVG " + g_smc.fvg_type;
    if(g_smc.fvg_tier != "")
        label += " [" + g_smc.fvg_tier + "]";
    if(g_smc.fvg_tier_score > 0)
        label += " (" + DoubleToString(g_smc.fvg_tier_score, 0) + ")";

    AddLabel(name + "_lbl", label, startTime, g_smc.fvg_high, clr, 8);
}

//+------------------------------------------------------------------+
//| DRAW LIQUIDITY SWEEP                                             |
//+------------------------------------------------------------------+
void DrawLiquiditySweep(datetime endTime)
{
    if(g_smc.ls_level <= 0) return;

    color clr = (g_smc.ls_type == "BULLISH_SWEEP") ? SweepBullColor : SweepBearColor;
    string name = g_prefix + "SWEEP";

    datetime startTime = GetStartTime(10);

    // Draw sweep level line
    CreateHLine(name, g_smc.ls_level, clr, STYLE_DASHDOTDOT, 2);

    // Draw arrow at sweep level
    string arrowName = name + "_arrow";
    bool isBullish = (g_smc.ls_type == "BULLISH_SWEEP");
    int arrowCode = isBullish ? 233 : 234; // Up arrow or down arrow

    if(ObjectCreate(0, arrowName, OBJ_ARROW, 0, startTime, g_smc.ls_level))
    {
        ObjectSetInteger(0, arrowName, OBJPROP_ARROWCODE, arrowCode);
        ObjectSetInteger(0, arrowName, OBJPROP_COLOR, clr);
        ObjectSetInteger(0, arrowName, OBJPROP_WIDTH, 2);
        ObjectSetInteger(0, arrowName, OBJPROP_ANCHOR, isBullish ? ANCHOR_TOP : ANCHOR_BOTTOM);
    }

    // Add label
    string label = "Liquidity Sweep: " + g_smc.ls_type;
    AddLabel(name + "_lbl", label, startTime, g_smc.ls_level, clr, 8);
}

//+------------------------------------------------------------------+
//| DRAW MARKET STRUCTURE (BOS / CHoCH)                              |
//+------------------------------------------------------------------+
void DrawMarketStructure(datetime endTime)
{
    // Draw swing high line
    if(g_smc.ms_swing_high > 0)
    {
        string shName = g_prefix + "MS_SWING_HIGH";
        CreateHLine(shName, g_smc.ms_swing_high, SwingHighColor, STYLE_DASH, 1);
        AddLabel(shName + "_lbl", "Swing High", GetStartTime(50), g_smc.ms_swing_high, SwingHighColor, 7);
    }

    // Draw swing low line
    if(g_smc.ms_swing_low > 0)
    {
        string slName = g_prefix + "MS_SWING_LOW";
        CreateHLine(slName, g_smc.ms_swing_low, SwingLowColor, STYLE_DASH, 1);
        AddLabel(slName + "_lbl", "Swing Low", GetStartTime(50), g_smc.ms_swing_low, SwingLowColor, 7);
    }

    // Draw BOS or CHoCH event
    if(g_smc.ms_last_event != "")
    {
        bool isBOS = (StringFind(g_smc.ms_last_event, "BOS") >= 0);
        bool isBullish = (StringFind(g_smc.ms_last_event, "BULLISH") >= 0);
        color eventClr = isBOS ? BOSColor : CHoCHColor;

        string eventName = g_prefix + "MS_EVENT";
        double eventLevel = 0;
        datetime eventTime = GetStartTime(5);

        if(isBullish && g_smc.ms_swing_high > 0)
            eventLevel = g_smc.ms_swing_high;
        else if(!isBullish && g_smc.ms_swing_low > 0)
            eventLevel = g_smc.ms_swing_low;

        if(eventLevel > 0)
        {
            // Draw event line
            CreateTrendLine(eventName, eventTime, eventLevel, endTime, eventLevel, eventClr, STYLE_SOLID, 2);

            // Draw arrow
            string arrowName = eventName + "_arrow";
            int arrowCode = isBullish ? 217 : 218; // Up or down arrow
            if(ObjectCreate(0, arrowName, OBJ_ARROW, 0, eventTime, eventLevel))
            {
                ObjectSetInteger(0, arrowName, OBJPROP_ARROWCODE, arrowCode);
                ObjectSetInteger(0, arrowName, OBJPROP_COLOR, eventClr);
                ObjectSetInteger(0, arrowName, OBJPROP_WIDTH, 3);
            }

            // Add label
            string label = g_smc.ms_last_event;
            AddLabel(eventName + "_lbl", label, eventTime, eventLevel, eventClr, 10);
        }
    }

    // Draw structure label
    string structName = g_prefix + "MS_STRUCTURE";
    color structClr = clrWhite;
    if(g_smc.ms_structure == "BULLISH") structClr = clrLime;
    else if(g_smc.ms_structure == "BEARISH") structClr = clrRed;
    else structClr = clrGray;

    AddLabel(structName, "Structure: " + g_smc.ms_structure, GetStartTime(80), g_smc.ms_swing_high, structClr, 9);
}

//+------------------------------------------------------------------+
//| DRAW SWING POINTS                                                |
//+------------------------------------------------------------------+
void DrawSwingPoints(datetime endTime)
{
    // Swing High
    if(g_smc.ms_swing_high > 0)
    {
        string name = g_prefix + "SWING_HIGH_PT";
        datetime t = GetStartTime(20);
        if(ObjectCreate(0, name, OBJ_ARROW_LEFT_PRICE, 0, t, g_smc.ms_swing_high))
        {
            ObjectSetInteger(0, name, OBJPROP_COLOR, SwingHighColor);
            ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
        }
    }

    // Swing Low
    if(g_smc.ms_swing_low > 0)
    {
        string name = g_prefix + "SWING_LOW_PT";
        datetime t = GetStartTime(20);
        if(ObjectCreate(0, name, OBJ_ARROW_LEFT_PRICE, 0, t, g_smc.ms_swing_low))
        {
            ObjectSetInteger(0, name, OBJPROP_COLOR, SwingLowColor);
            ObjectSetInteger(0, name, OBJPROP_WIDTH, 1);
        }
    }
}

//+------------------------------------------------------------------+
//| DRAW INFO LABEL (top-left corner)                                |
//+------------------------------------------------------------------+
void DrawInfoLabel(datetime endTime)
{
    string name = g_prefix + "INFO";

    string text = "═══ SMC ANALYSIS ═══\n";
    text += "Symbol: " + g_smc.symbol + "\n";
    text += "Structure: " + g_smc.ms_structure + "\n";
    text += "Event: " + (g_smc.ms_last_event == "" ? "None" : g_smc.ms_last_event) + "\n";
    text += "Recommendation: " + g_smc.recommendation + "\n";
    text += "Confluence: " + IntegerToString(g_smc.confluence_count) + " signals (" + DoubleToString(g_smc.confluence_score, 1) + "%)\n";
    text += "Zone: " + g_smc.pd_zone + " (" + DoubleToString(g_smc.pd_position_pct, 1) + "%)\n";

    if(g_smc.ls_swept)
        text += "⚠ LIQUIDITY SWEEP: " + g_smc.ls_type + "\n";

    if(g_smc.fvg_has)
        text += "FVG: " + g_smc.fvg_type + " [" + g_smc.fvg_tier + "]\n";

    if(g_smc.price_in_bull_ob)
        text += "★ Price in Bullish OB\n";
    if(g_smc.price_in_bear_ob)
        text += "★ Price in Bearish OB\n";

    // Update time
    if(g_smc.update_time > 0)
        text += "Updated: " + TimeToString(g_smc.update_time, TIME_DATE | TIME_MINUTES);

    if(ObjectFind(0, name) < 0)
    {
        ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
        ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
        ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 10);
        ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 20);
        ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 9);
        ObjectSetString(0, name, OBJPROP_FONT, "Consolas");
    }

    // Set color based on recommendation
    color txtClr = clrWhite;
    if(g_smc.recommendation == "BULLISH") txtClr = clrLime;
    else if(g_smc.recommendation == "BEARISH") txtClr = clrRed;

    ObjectSetString(0, name, OBJPROP_TEXT, text);
    ObjectSetInteger(0, name, OBJPROP_COLOR, txtClr);
    ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

//+------------------------------------------------------------------+
//| HELPER: CREATE RECTANGLE                                         |
//+------------------------------------------------------------------+
void CreateRectangle(string name, datetime t1, double p1, datetime t2, double p2,
                     color clr, bool fill, color fillColor, int width, int style, int transparency)
{
    if(ObjectFind(0, name) >= 0)
        ObjectDelete(0, name);

    if(ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2))
    {
        ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
        ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
        ObjectSetInteger(0, name, OBJPROP_STYLE, style);
        ObjectSetInteger(0, name, OBJPROP_FILL, fill);
        ObjectSetInteger(0, name, OBJPROP_BACK, true);
        ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
        ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);

        // Set transparency (MT5 5+ only)
        ObjectSetInteger(0, name, OBJPROP_BACK, true);
    }
}

//+------------------------------------------------------------------+
//| HELPER: CREATE HORIZONTAL LINE                                   |
//+------------------------------------------------------------------+
void CreateHLine(string name, double price, color clr, int style, int width)
{
    if(ObjectFind(0, name) >= 0)
        ObjectDelete(0, name);

    if(ObjectCreate(0, name, OBJ_HLINE, 0, 0, price))
    {
        ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
        ObjectSetInteger(0, name, OBJPROP_STYLE, style);
        ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
        ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
        ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
    }
}

//+------------------------------------------------------------------+
//| HELPER: CREATE TREND LINE                                        |
//+------------------------------------------------------------------+
void CreateTrendLine(string name, datetime t1, double p1, datetime t2, double p2,
                     color clr, int style, int width)
{
    if(ObjectFind(0, name) >= 0)
        ObjectDelete(0, name);

    if(ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2))
    {
        ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
        ObjectSetInteger(0, name, OBJPROP_STYLE, style);
        ObjectSetInteger(0, name, OBJPROP_WIDTH, width);
        ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
        ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
        ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
    }
}

//+------------------------------------------------------------------+
//| HELPER: ADD TEXT LABEL                                           |
//+------------------------------------------------------------------+
void AddLabel(string name, string text, datetime time, double price, color clr, int fontSize)
{
    string lblName = name + "_text";
    if(ObjectFind(0, lblName) >= 0)
        ObjectDelete(0, lblName);

    if(ObjectCreate(0, lblName, OBJ_TEXT, 0, time, price))
    {
        ObjectSetString(0, lblName, OBJPROP_TEXT, text);
        ObjectSetInteger(0, lblName, OBJPROP_COLOR, clr);
        ObjectSetInteger(0, lblName, OBJPROP_FONTSIZE, fontSize);
        ObjectSetInteger(0, lblName, OBJPROP_SELECTABLE, false);
        ObjectSetInteger(0, lblName, OBJPROP_HIDDEN, true);
        ObjectSetInteger(0, lblName, OBJPROP_ANCHOR, ANCHOR_LEFT_LOWER);
    }
}

//+------------------------------------------------------------------+
//| HELPER: GET START TIME (bars back from current)                  |
//+------------------------------------------------------------------+
datetime GetStartTime(int barsBack)
{
    datetime result = 0;
    int shift = barsBack;
    if(shift < 0) shift = 0;

    datetime barTime = (datetime)SeriesInfoInteger(_Symbol, _Period, SERIES_LASTBAR_DATE);
    result = barTime - (datetime)(PeriodSeconds() * shift);

    return result;
}

//+------------------------------------------------------------------+
//| REMOVE ALL SMC OBJECTS FROM CHART                                |
//+------------------------------------------------------------------+
void RemoveAllObjects()
{
    int total = ObjectsTotal(0, 0, -1);
    for(int i = total - 1; i >= 0; i--)
    {
        string name = ObjectName(0, i, 0, -1);
        if(StringFind(name, g_prefix) == 0)
            ObjectDelete(0, name);
    }
}
//+------------------------------------------------------------------+