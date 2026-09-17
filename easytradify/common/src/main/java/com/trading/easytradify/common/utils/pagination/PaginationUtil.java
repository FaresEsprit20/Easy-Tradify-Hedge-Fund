package com.trading.easytradify.common.utils.pagination;

import com.trading.easytradify.common.exception.ErrorCodes;
import com.trading.easytradify.common.exception.InvalidEntityException;
import com.trading.easytradify.common.utils.pagination.enums.SortingDirection;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;

import java.util.ArrayList;
import java.util.List;

public class PaginationUtil {

    public static Pageable createPageRequest(PaginationAndFilteringDto dto) {

        List<String> errors = new ArrayList<>();

        if (dto.getPage() < 1) {
            errors.add("page must be greater than 0");
        }

        if (!dto.getSortDirection().equals(SortingDirection.ASC) &&
                !dto.getSortDirection().equals(SortingDirection.DESC)) {
            errors.add("sortDirection must be ASC or DESC");
        }

        if (!errors.isEmpty()) {
            throw new InvalidEntityException("Invalid pagination or sorting parameters",
                    ErrorCodes.PAGE_NOT_VALID, errors);
        }

        Sort sort = dto.getSortDirection() == SortingDirection.ASC
                ? Sort.by(dto.getSortField()).ascending()
                : Sort.by(dto.getSortField()).descending();

        return PageRequest.of(dto.getPage() - 1, dto.getSize(), sort);
    }


}

