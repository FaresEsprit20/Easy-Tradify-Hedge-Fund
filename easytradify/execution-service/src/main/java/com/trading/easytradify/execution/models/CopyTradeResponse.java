package com.trading.easytradify.execution.models;

public record CopyTradeResponse(
        boolean success,
        String symbol,
        Integer ticket,
        Double entryPrice,
        Double stopLoss,
        Double takeProfit,
        Double volume,
        String error
) {
    public static CopyTradeResponse success(String symbol, Integer ticket, Double entryPrice,
                                            Double stopLoss, Double takeProfit, Double volume) {
        return new CopyTradeResponse(true, symbol, ticket, entryPrice, stopLoss, takeProfit, volume, null);
    }

    public static CopyTradeResponse error(String symbol, String error) {
        return new CopyTradeResponse(false, symbol, null, null, null, null, null, error);
    }

}