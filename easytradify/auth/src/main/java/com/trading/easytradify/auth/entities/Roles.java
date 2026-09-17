package com.trading.easytradify.auth.entities;

import com.trading.easytradify.auth.entities.enums.UserRole;
import com.trading.easytradify.common.entities.AbstractEntity;
import jakarta.persistence.*;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.EqualsAndHashCode;
import lombok.NoArgsConstructor;

@Data
@NoArgsConstructor
@AllArgsConstructor
@EqualsAndHashCode(callSuper = true)
@Entity
@Table(name = "roles")
public class Roles extends AbstractEntity {

    @Column(name = "role_name")
    @Enumerated(EnumType.STRING)
    private UserRole roleName;



}