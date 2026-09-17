package com.trading.easytradify.auth.dto.roles;

import com.trading.easytradify.auth.entities.Roles;
import com.trading.easytradify.auth.entities.enums.UserRole;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

@AllArgsConstructor
@NoArgsConstructor
@Data
public class RolesDto {

    private Integer id;
    private UserRole roleName;

    // Static conversion methods with default values
    public static RolesDto fromEntity(Roles roles) {
        if (roles == null) {
            return null;
        }
        return new RolesDto(
                roles.getId() != null ? roles.getId() : 0,  // Default to 0 if null
                roles.getRoleName() != null ? roles.getRoleName() : UserRole.USER  // Default to UserRole.USER if null
        );
    }

    public static Roles toEntity(RolesDto rolesDto) {
        if (rolesDto == null) {
            return null;
        }
        Roles roles = new Roles();
        roles.setRoleName(rolesDto.getRoleName() != null ? rolesDto.getRoleName() : UserRole.USER);  // Default to UserRole.USER if null
        return roles;
    }


}
