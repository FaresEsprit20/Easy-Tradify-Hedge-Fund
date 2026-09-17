package com.trading.easytradify.common.utils.pagination;

import com.trading.easytradify.common.utils.pagination.enums.SortingDirection;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import lombok.Data;

import java.util.Map;

@Data
public class PaginationAndFilteringDto {

    @NotNull(message = "Page number is required")
    @Min(value = 1, message = "Page number must be greater than 0")
    private Integer page = 1;

    @NotNull(message = "Page size is required")
    @Min(value = 1, message = "Page size must be at least 1")
    @Max(value = 100, message = "Page size cannot exceed 100")
    private Integer size = 10;

    private String sortField = "id";

    private SortingDirection sortDirection = SortingDirection.DESC;

    private Map<String, String> filters;
}