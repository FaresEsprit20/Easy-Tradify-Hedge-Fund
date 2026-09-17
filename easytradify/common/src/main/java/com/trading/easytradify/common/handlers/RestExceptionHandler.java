package com.trading.easytradify.common.handlers;

import com.trading.easytradify.common.exception.*;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.ConstraintViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.context.request.WebRequest;
import org.springframework.web.servlet.mvc.method.annotation.ResponseEntityExceptionHandler;

import java.sql.SQLException;
import java.util.List;
import java.util.stream.Collectors;

@RestControllerAdvice
public class RestExceptionHandler extends ResponseEntityExceptionHandler {

    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<CustomErrorMsg> handleConstraintViolationException(ConstraintViolationException exception, WebRequest webRequest) {
        final HttpStatus badRequest = HttpStatus.BAD_REQUEST;

        List<String> errors = exception.getConstraintViolations().stream()
                .map(ConstraintViolation::getMessage)
                .collect(Collectors.toList());

        final CustomErrorMsg errorDto = new CustomErrorMsg();
        errorDto.setCode(ErrorCodes.INVALID_PARAMETER);
        errorDto.setHttpCode(badRequest.value());
        errorDto.setMessage("Validation failed: " + (errors.isEmpty() ? "Invalid parameter(s)" : errors.get(0)));
        errorDto.setErrors(errors);

        return new ResponseEntity<>(errorDto, badRequest);
    }

    @ExceptionHandler(EntityNotFoundException.class)
    public ResponseEntity<CustomErrorMsg> handleException(EntityNotFoundException exception, WebRequest webRequest) {
        final HttpStatus notFound = HttpStatus.NOT_FOUND;
        final CustomErrorMsg errorDto = new CustomErrorMsg();
        errorDto.setCode(exception.getErrorCode());
        errorDto.setHttpCode(notFound.value());
        errorDto.setMessage(exception.getMessage());
        errorDto.setErrors(exception.getErrors());
        return new ResponseEntity<>(errorDto, notFound);
    }

    @ExceptionHandler(InvalidOperationException.class)
    public ResponseEntity<CustomErrorMsg> handleException(InvalidOperationException exception, WebRequest webRequest) {
        final HttpStatus notFound = HttpStatus.BAD_REQUEST;
        final CustomErrorMsg errorDto = new CustomErrorMsg();
        errorDto.setCode(exception.getErrorCode());
        errorDto.setHttpCode(notFound.value());
        errorDto.setMessage(exception.getMessage());
        errorDto.setErrors(exception.getErrors());
        return new ResponseEntity<>(errorDto, notFound);
    }

    @ExceptionHandler(InvalidEntityException.class)
    public ResponseEntity<CustomErrorMsg> handleException(InvalidEntityException exception, WebRequest webRequest) {
        final HttpStatus badRequest = HttpStatus.BAD_REQUEST;
        final CustomErrorMsg errorDto = new CustomErrorMsg();
        errorDto.setCode(exception.getErrorCode());
        errorDto.setHttpCode(badRequest.value());
        errorDto.setMessage(exception.getMessage());
        errorDto.setErrors(exception.getErrors());
        return new ResponseEntity<>(errorDto, badRequest);
    }

    // New handler for TradingException
    @ExceptionHandler(TradingException.class)
    public ResponseEntity<CustomErrorMsg> handleTradingException(TradingException exception, WebRequest webRequest) {
        HttpStatus httpStatus;

        // Map error codes to appropriate HTTP status codes
        if (exception.getErrorCode().getCode() >= 37000 && exception.getErrorCode().getCode() <= 37099) {
            // MT5 Connection errors -> Service Unavailable
            httpStatus = HttpStatus.SERVICE_UNAVAILABLE;
        } else if (exception.getErrorCode().getCode() >= 37100 && exception.getErrorCode().getCode() <= 37199) {
            // Symbol errors -> Not Found or Bad Request
            httpStatus = exception.getErrorCode() == ErrorCodes.SYMBOL_NOT_FOUND ?
                    HttpStatus.NOT_FOUND : HttpStatus.BAD_REQUEST;
        } else if (exception.getErrorCode().getCode() >= 37200 && exception.getErrorCode().getCode() <= 37299) {
            // Trade execution errors -> Bad Request or Too Many Requests
            httpStatus = exception.getErrorCode() == ErrorCodes.MAX_TRADES_REACHED ?
                    HttpStatus.TOO_MANY_REQUESTS : HttpStatus.BAD_REQUEST;
        } else if (exception.getErrorCode().getCode() >= 37300 && exception.getErrorCode().getCode() <= 37399) {
            // Position errors -> Not Found or Bad Request
            httpStatus = exception.getErrorCode() == ErrorCodes.POSITION_NOT_FOUND ?
                    HttpStatus.NOT_FOUND : HttpStatus.BAD_REQUEST;
        } else if (exception.getErrorCode().getCode() >= 37600 && exception.getErrorCode().getCode() <= 37699) {
            // Account errors -> Forbidden or Bad Request
            httpStatus = HttpStatus.FORBIDDEN;
        } else if (exception.getErrorCode().getCode() >= 37800 && exception.getErrorCode().getCode() <= 37899) {
            // Rate limiting errors -> Too Many Requests
            httpStatus = HttpStatus.TOO_MANY_REQUESTS;
        } else {
            httpStatus = HttpStatus.BAD_REQUEST;
        }

        final CustomErrorMsg errorDto = new CustomErrorMsg();
        errorDto.setCode(exception.getErrorCode());
        errorDto.setHttpCode(httpStatus.value());
        errorDto.setMessage(exception.getMessage());
        errorDto.setErrors(exception.getErrors());

        // Add additional details if available
        if (exception.getMt5RetCode() != null) {
            errorDto.getErrors().add("MT5 Error Code: " + exception.getMt5RetCode());
        }
        if (exception.getSymbol() != null) {
            errorDto.getErrors().add("Symbol: " + exception.getSymbol());
        }
        if (exception.getTicket() != null) {
            errorDto.getErrors().add("Ticket: " + exception.getTicket());
        }

        return new ResponseEntity<>(errorDto, httpStatus);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<String> handleIllegalArgumentException(IllegalArgumentException ex) {
        return ResponseEntity
                .badRequest()
                .body(ex.getMessage());
    }

    @ExceptionHandler(SQLException.class)
    public ResponseEntity<CustomErrorMsg> handleSQLException(SQLException exception, WebRequest webRequest) {
        final HttpStatus internalServerError = HttpStatus.INTERNAL_SERVER_ERROR;
        String rawMsg = exception.getMessage();
        String safeMsg;
        if (rawMsg != null && rawMsg.contains("Detail:")) {
            safeMsg = rawMsg.substring(rawMsg.indexOf("Detail:") + 7).trim();
        } else {
            safeMsg = "A database error occurred while processing your request.";
        }
        final CustomErrorMsg errorDto = CustomErrorMsg.builder()
                .code(ErrorCodes.DATABASE_ERROR)
                .httpCode(internalServerError.value())
                .message("Database error occurred: " + safeMsg)
                .build();
        return new ResponseEntity<>(errorDto, internalServerError);
    }

    @ExceptionHandler(RecaptchaException.class)
    public ResponseEntity<CustomErrorMsg> handleException(RecaptchaException exception, WebRequest webRequest) {
        final HttpStatus badRequest = HttpStatus.BAD_REQUEST;
        final CustomErrorMsg errorDto = new CustomErrorMsg();
        errorDto.setCode(exception.getErrorCode());
        errorDto.setHttpCode(badRequest.value());
        errorDto.setMessage(exception.getMessage());
        errorDto.setErrors(exception.getErrors());
        return new ResponseEntity<>(errorDto, badRequest);
    }

}