SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;
SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;
SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='TRADITIONAL,ALLOW_INVALID_DATES';

CREATE SCHEMA IF NOT EXISTS `CloudFlowPortal` DEFAULT CHARACTER SET latin1 ;
USE `CloudFlowPortal` ;

-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblEntities`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblEntities` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `created_at` TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NULL,
  `deleted_at` TIMESTAMP NULL,
  `deleted` TINYINT NULL DEFAULT 0,
  `ParentEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `EntityType` VARCHAR(50) NULL COMMENT ' /* comment truncated */ /*Must be set to slice, organization,department, vdc*/',
  `Name` VARCHAR(500) NULL,
  `Description` VARCHAR(500) NULL,
  `EntityStatus` VARCHAR(300) NULL DEFAULT 'Ready',
  `UniqueId` VARCHAR(64) NULL,
  `EntityDisabled` TINYINT NULL DEFAULT 0 COMMENT ' /* comment truncated */ /*0 = Enabled; 1=Disabled*/',
  `SortSequenceId` INT UNSIGNED NULL DEFAULT 0 COMMENT ' /* comment truncated */ /*entity priority within the same type of entities*/',
  `EntitySubType` VARCHAR(45) NULL,
  `ClonedFromEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `EntityMode` VARCHAR(45) NULL DEFAULT 'Ready',
  `EntityBridgeId` BIGINT UNSIGNED NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblUsers`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblUsers` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `UserName` VARCHAR(45) NULL,
  `LoginId` VARCHAR(64) NULL,
  `Locked` TINYINT NULL DEFAULT 0 COMMENT ' /* comment truncated */ /*0 = Unlocked; 1=Locked*/',
  `Token` MEDIUMTEXT NULL,
  `TokenIssuedAt` DATETIME NULL,
  `TokenExpiresAt` DATETIME NULL,
  `IsAnonymous` TINYINT(1) NULL DEFAULT '0',
  `LastActivityDate` DATETIME NULL,
  `UsersExcludeFlg` TINYINT(1) NULL DEFAULT '0',
  `UsersReadOnlyFlg` TINYINT(1) NULL DEFAULT '0',
  `UsersPrivateFlg` TINYINT(1) NULL DEFAULT '0',
  `RecCreatedBy` BIGINT UNSIGNED NULL DEFAULT 0,
  `RecLastUpdateBy` BIGINT UNSIGNED NULL DEFAULT 0,
  `RecLastUpdateDt` DATETIME NULL,
  `UserIPAddress` VARCHAR(512) NULL,
  `SelectedOrganizationEntityId` BIGINT NULL DEFAULT 0,
  `email` VARCHAR(512) NULL,
  `Boot_Storage_Type` VARCHAR(100) NULL DEFAULT 'Ephemeral' COMMENT ' /* comment truncated */ /*0 = Ephemral; 1=ContainerVolume*/',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  INDEX `userEntity_idx` (`tblEntities` ASC),
  CONSTRAINT `userEntity`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblACLRules`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblACLRules` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `From_Port` INT NULL DEFAULT 0,
  `To_Port` INT NULL DEFAULT 0,
  `Source_Ip` VARCHAR(50) NULL DEFAULT '0.0.0.0',
  `Destination_Ip` VARCHAR(50) NULL DEFAULT '0.0.0.0',
  `Action` VARCHAR(50) NULL DEFAULT 'Allow',
  `Protocol` VARCHAR(20) NULL DEFAULT 'TCP',
  `Traffic_Direction` VARCHAR(50) NULL DEFAULT 'Ingress',
  `RedirectHost` VARCHAR(200) NULL DEFAULT 'False',
  `Service` VARCHAR(100) NULL DEFAULT 'Custom',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entityacl_idx` (`tblEntities` ASC),
  CONSTRAINT `entityacl`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblBuckets`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblBuckets` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `Capacity` INT NULL DEFAULT 20,
  `DefaultSliceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entitybucket_idx` (`tblEntities` ASC),
  CONSTRAINT `entitybucket`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblSlices`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblSlices` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `URL` VARCHAR(500) NULL,
  `Physical_mgmt_port` VARCHAR(45) NULL,
  `Virtual_mgmt_port` VARCHAR(45) NULL,
  `Inter_slice_mgmt_port` VARCHAR(45) NULL,
  `Inter_slice_vpn_port` VARCHAR(45) NULL,
  `Ip_address` VARCHAR(45) NULL,
  `virtual_infrastructure_url` VARCHAR(500) NULL,
  `physical_infrastructure_url` VARCHAR(500) NULL,
  `Administrator` VARCHAR(500) NULL,
  `Email` VARCHAR(500) NULL,
  `Location` VARCHAR(500) NULL,
  `firmware_version` VARCHAR(45) NULL,
  `ResyncInProgress` TINYINT NULL DEFAULT 0,
  `LastResyncTime` DATETIME NULL,
  `Slice_created_at` DATETIME NULL,
  `Slice_updated_at` DATETIME NULL,
  `last_log_time` DATETIME NULL,
  `HawkResyncTime` DATETIME NULL,
  `ResyncIntervalSeconds` INT NULL DEFAULT 30,
  PRIMARY KEY (`id`),
  INDEX `FK_tblSlices_tblEntities` (`tblEntities` ASC),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  CONSTRAINT `FK_tblSlices_tblEntities`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblContainers`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblContainers` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL COMMENT ' /* comment truncated */ /*Organization Id or Department Id*/',
  `Capacity` INT NULL DEFAULT 20,
  `Iops` INT NULL DEFAULT 0,
  `Latency` VARCHAR(100) NULL DEFAULT 'Gold',
  `ContainerType` VARCHAR(100) NULL DEFAULT 'Regular',
  `Security` VARCHAR(100) NULL DEFAULT 'None',
  `DataReduction` VARCHAR(100) NULL DEFAULT 'None',
  `DefaultSliceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `StorageClass` VARCHAR(45) NULL DEFAULT 'Gold',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `enttiyContainer_idx` (`tblEntities` ASC),
  CONSTRAINT `enttiyContainer`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblDepartments`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblDepartments` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NOT NULL,
  `DefaultSliceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `Administrator` VARCHAR(500) NULL,
  `Email` VARCHAR(500) NULL,
  `Location` VARCHAR(500) NULL,
  `last_log_time` DATETIME NULL,
  `HawkResyncTime` DATETIME NULL,
  `ResyncIntervalSeconds` INT NULL DEFAULT 30,
  PRIMARY KEY (`id`),
  INDEX `FK_tblDepartments_tblEntities` (`tblEntities` ASC),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  CONSTRAINT `FK_tblDepartments_tblEntities`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblDisks`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblDisks` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `Capacity` INT NULL DEFAULT 20,
  `DefaultSliceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entityDisk_idx` (`tblEntities` ASC),
  CONSTRAINT `entityDisk`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblEntityAllocations`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblEntityAllocations` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `ParentEntityId` BIGINT(20) NULL DEFAULT '0',
  `EntityId` BIGINT(20) NULL DEFAULT '0',
  `ServiceId` BIGINT(20) NULL DEFAULT '0',
  `ResourceType` INT(11) NULL DEFAULT '0',
  `ResourceValue` BIGINT(20) NULL DEFAULT '0',
  `StorageCapacity` BIGINT(20) NULL,
  `StorageIOPS` BIGINT(20) NULL,
  `StorageNetwork` BIGINT(20) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblAttachedEntities`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblAttachedEntities` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `AttachedEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `AttachedSortSequenceId` INT NULL DEFAULT 0 COMMENT ' /* comment truncated */ /*entity priority within the same type of entities*/',
  `IPAddressType` VARCHAR(45) NULL DEFAULT 'Dynamic',
  `StaticIPAddress` VARCHAR(15) NULL DEFAULT '0.0.0.0',
  `AttachedEntityUniqueId` VARCHAR(45) NULL,
  `AttachedEntityGrandparentName` VARCHAR(512) NULL,
  `AttachedEntityParentName` VARCHAR(512) NULL,
  `AttachedEntityName` VARCHAR(512) NULL,
  `AttachedEntityType` VARCHAR(45) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entityMapping_idx` (`tblEntities` ASC),
  CONSTRAINT `entityGroups`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblServicePorts`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblServicePorts` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `DestinationServiceEntityId` BIGINT NULL DEFAULT 0,
  `ServiceInterfaceEntityId` BIGINT NULL DEFAULT 0,
  `InterfacePortIndex` INT NULL DEFAULT 0,
  `GuarBandwidth` INT NULL DEFAULT 0,
  `MaxBandwidth` INT NULL DEFAULT 0,
  `IPSConnectionType` INT NULL,
  `SecurityZone` VARCHAR(45) NULL DEFAULT 'Untrusted',
  `InterfacePriority` VARCHAR(100) NULL DEFAULT 'Silver',
  `MaxIOPS` INT NULL DEFAULT 0,
  `GuarIOPS` INT NULL DEFAULT 0,
  `Qos` VARCHAR(45) NULL DEFAULT 'Normal',
  `interface_type` VARCHAR(45) NULL DEFAULT 'Default' COMMENT ' /* comment truncated */ /*This is set during the validation phase to north or south bound - depening upon where the "public" interface is available*/',
  `mtu` INT NULL DEFAULT 1450,
  `FinalDestinationServiceId` BIGINT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  INDEX `svcconEntity_idx` (`tblEntities` ASC),
  CONSTRAINT `svcconEntity`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblKeyValuePairs`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblKeyValuePairs` (
  `id` BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `TheKey` LONGTEXT NULL,
  `TheValue` LONGTEXT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  INDEX `entity_KV_idx` (`tblEntities` ASC),
  CONSTRAINT `entity_KV`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblLBSServices`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblLBSServices` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `Protocol` VARCHAR(50) NULL DEFAULT 'TCP',
  `Port` INT NULL DEFAULT 80,
  `Method` VARCHAR(100) NULL DEFAULT 'Weighted Round Robin',
  `Health_Monitor` VARCHAR(20) NULL DEFAULT 'TCP',
  `Health_Check_Interval` INT NULL DEFAULT 60,
  `Health_Check_Retries` INT NULL DEFAULT 5,
  `Persistence` VARCHAR(45) NULL DEFAULT 'Disabled',
  `PersistenceTimeout` INT NULL DEFAULT 360,
  `HTTP_Check_URL` VARCHAR(512) NULL DEFAULT '',
  `lbs_mode` VARCHAR(45) NULL DEFAULT 'Layer 4',
  `frontend_timeout` INT NULL DEFAULT 10000,
  `frontend_mode` VARCHAR(45) NULL DEFAULT 'Keep Alive',
  `frontend_cookie` VARCHAR(45) NULL DEFAULT 'Enabled',
  `frontend_accept_proxy` VARCHAR(45) NULL DEFAULT 'Disabled',
  `backend_port` INT NULL DEFAULT 0,
  `backend_mode` VARCHAR(45) NULL DEFAULT 'Keep Alive',
  `backend_timeout` INT NULL DEFAULT 10000,
  `backend_connect_timeout` INT NULL DEFAULT 5000,
  `backend_connect_retries` INT NULL DEFAULT 5,
  `backend_forwardfor` VARCHAR(45) NULL DEFAULT 'Enabled',
  `backend_send_proxy` VARCHAR(45) NULL DEFAULT 'Disabled',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entity_lbs_idx` (`tblEntities` ASC),
  CONSTRAINT `entity_lbs`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB
AUTO_INCREMENT = 1036;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblLibraries`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblLibraries` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `MasterSlice_idx` (`tblEntities` ASC),
  CONSTRAINT `MasterSlice`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblLibraryImages`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblLibraryImages` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `uuid` VARCHAR(36) NULL,
  `ImageType` VARCHAR(100) NULL,
  `OSType` VARCHAR(100) NULL,
  `Version` VARCHAR(100) NULL,
  `disk_format` VARCHAR(100) NULL DEFAULT 'QCOW2',
  `container_format` VARCHAR(100) NULL DEFAULT 'bare',
  `image_size` BIGINT NULL DEFAULT 0,
  `architecture` VARCHAR(100) NULL DEFAULT 'x86_64',
  `image_state` VARCHAR(100) NULL,
  `min_disk` INT NULL DEFAULT 0,
  `min_ram` INT NULL DEFAULT 0,
  `image_path` VARCHAR(240) NULL,
  `uri` VARCHAR(1024) NULL,
  `glance_token` TEXT NULL,
  `glance_token_expires_at` VARCHAR(64) NULL,
  `glance_url` VARCHAR(512) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `LibImageId_UNIQUE` (`id` ASC),
  INDEX `parenttblEn_idx` (`tblEntities` ASC),
  CONSTRAINT `parenttblEn`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblMonitorWidgetServiceConfig`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblMonitorWidgetServiceConfig` (
  `WConfigId` BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `EntityId` BIGINT(20) UNSIGNED NOT NULL,
  `ServiceId` BIGINT(20) UNSIGNED NOT NULL,
  `ConfigLevelType` INT(11) NOT NULL DEFAULT '0',
  `MonitorType` INT(11) NOT NULL DEFAULT '0',
  `MonitorIndex` INT(11) NOT NULL DEFAULT '0',
  `InterfaceIndex` INT(11) NOT NULL,
  `ChildIndex` INT(11) NOT NULL,
  `GrandChildIndex` INT(11) NOT NULL,
  `UniqueId` VARCHAR(64) NULL DEFAULT NULL,
  `created_at` DATETIME NULL DEFAULT NULL,
  PRIMARY KEY (`WConfigId`),
  UNIQUE INDEX `UniqueId` (`UniqueId` ASC),
  INDEX `svcid_idx` (`ServiceId` ASC),
  CONSTRAINT `svcid`
    FOREIGN KEY (`ServiceId`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblAttachedNetworkEntities`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblAttachedNetworkEntities` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `NetworkType` VARCHAR(100) NULL,
  `TotalBandwidth` INT NULL DEFAULT 0,
  `CurrentBandwidth` INT NULL DEFAULT 0,
  `IPAddress` VARCHAR(45) NULL,
  `IPMask` VARCHAR(45) NULL,
  `uri` VARCHAR(1024) NULL,
  `foreign_addresses` VARCHAR(2048) NULL DEFAULT '',
  `network_address` VARCHAR(45) NULL,
  `network_mask` VARCHAR(45) NULL,
  `user_foreign_addresses` VARCHAR(2048) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  INDEX `extenalNetEn_idx` (`tblEntities` ASC),
  CONSTRAINT `extenalNetEn`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblNetworksEntitiesMappings`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblNetworksEntitiesMappings` (
  `id` BIGINT(20) NOT NULL AUTO_INCREMENT,
  `NetworkUniqueId` VARCHAR(64) NOT NULL,
  `EntityUniqueId` VARCHAR(64) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `NetworkUniqueId` (`NetworkUniqueId` ASC),
  UNIQUE INDEX `EntityUniqueId` (`EntityUniqueId` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblBucketObjects`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblBucketObjects` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `Capacity` INT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entityBuckets_idx` (`tblEntities` ASC),
  CONSTRAINT `entityBuckets`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblOrganizations`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblOrganizations` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `DefaultSliceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `Administrator` VARCHAR(500) NULL,
  `Email` VARCHAR(500) NULL,
  `Location` VARCHAR(500) NULL,
  `last_log_time` DATETIME NULL,
  `flavors_enabled` TINYINT NULL DEFAULT 0,
  `HawkResyncTime` DATETIME NULL,
  `ResyncIntervalSeconds` INT NULL DEFAULT 30,
  PRIMARY KEY (`id`),
  INDEX `FK_tblOrganizations_tblCloudFlowEntities` (`tblEntities` ASC),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  CONSTRAINT `FK_tblOrganizations_tblCloudFlowEntities`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblDiskPartitions`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblDiskPartitions` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `Capacity` INT NULL DEFAULT 8,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entitylpartition_idx` (`tblEntities` ASC),
  CONSTRAINT `entitylpartition`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblSecurityRules`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblSecurityRules` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `Source_Ip` VARCHAR(254) NULL DEFAULT '0.0.0.0',
  `Destination_Ip` VARCHAR(254) NULL DEFAULT '0.0.0.0',
  `FW_Application` VARCHAR(100) NULL DEFAULT 'Custom',
  `From_Port` INT NULL DEFAULT 0,
  `To_Port` INT NULL DEFAULT 0,
  `Action` VARCHAR(50) NULL DEFAULT 'Allow' COMMENT ' /* comment truncated */ /*allow, deny, drop, tunnel
*/',
  `Protocol` VARCHAR(20) NULL DEFAULT 'TCP',
  `Traffic_Direction` VARCHAR(50) NULL DEFAULT 'Ingress',
  `Track` VARCHAR(100) NULL DEFAULT 'None',
  `Alarm_Threshold` INT NULL DEFAULT 0,
  `Start_Time` TIME NULL DEFAULT '2014-01-01 12:00:00',
  `Stop_Time` TIME NULL DEFAULT '2014-01-01 12:00:00',
  `VPNTunnelEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `Session_State` VARCHAR(512) NULL DEFAULT 'Any',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entity_fws_idx` (`tblEntities` ASC),
  CONSTRAINT `entity_fws`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblServerFarms`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblServerFarms` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `Scale_Option` VARCHAR(32) NULL DEFAULT 'Disabled' COMMENT ' /* comment truncated */ /*static;dynamic*/',
  `Initial` INT NULL DEFAULT 3,
  `Min` INT NULL DEFAULT 1,
  `Max` INT NULL DEFAULT 5,
  `DynOpBandwidth` TINYINT NULL DEFAULT 1 COMMENT ' /* comment truncated */ /*0 = Disabled; 1=Enabled*/',
  `DynOpCPU` TINYINT NULL DEFAULT 1,
  `DynOpRam` TINYINT NULL DEFAULT 1,
  `CPU_Red` INT NULL DEFAULT 75,
  `CPU_Green` INT NULL DEFAULT 60,
  `Bandwidth_Red` INT NULL DEFAULT 80,
  `Bandwidth_Green` INT NULL DEFAULT 60,
  `RAM_Red` INT NULL DEFAULT 80,
  `RAM_Green` INT NULL DEFAULT 50,
  `Homogenous` TINYINT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entitySfarm_idx` (`tblEntities` ASC),
  CONSTRAINT `entitySfarm`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblServers`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblServers` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `Hypervisor` VARCHAR(100) NULL DEFAULT 'KVM',
  `CPUVcpu` INT NULL DEFAULT 1,
  `CPUMHz` INT NULL DEFAULT 1024,
  `Memory` INT NULL DEFAULT 1024,
  `Boot_Storage_Type` VARCHAR(100) NULL DEFAULT 'Ephemeral' COMMENT ' /* comment truncated */ /*0 = Ephemral; 1=ContainerVolume*/',
  `ephemeral_storage` INT NULL DEFAULT 10,
  `BootVolumeEntityId` BIGINT NULL DEFAULT 0,
  `BootImageEntityId` BIGINT NULL DEFAULT 0,
  `BootVolumeUniqueId` VARCHAR(45) NULL,
  `BootImageUniqueId` VARCHAR(45) NULL,
  `User_Data` LONGTEXT NULL,
  `UUID` VARCHAR(100) NULL COMMENT ' /* comment truncated */ /*UUID as supplied by CFD*/',
  `xvpnc_url` VARCHAR(500) NULL,
  `novnc_url` VARCHAR(500) NULL,
  `server_status` VARCHAR(45) NULL,
  `vm_state` VARCHAR(45) NULL,
  `task_state` VARCHAR(45) NULL,
  `fault_code` INT NULL,
  `fault_details` VARCHAR(1024) NULL,
  `fault_message` VARCHAR(1024) NULL,
  `admin_password` VARCHAR(512) NULL DEFAULT '',
  `tblFlavors` BIGINT NULL DEFAULT 0,
  `weight` INT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entityServer_idx` (`tblEntities` ASC),
  CONSTRAINT `entityServer`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblComputeEntities`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblComputeEntities` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `Uuid` VARCHAR(45) NULL,
  `Hypervisor` VARCHAR(45) NULL,
  `Cores` INT NULL,
  `Mhz` INT NULL,
  `Sockets` INT NULL,
  `Memory` INT NULL,
  `Manufacturer` VARCHAR(256) NULL,
  `Model` VARCHAR(256) NULL,
  `TotalBandwidth` INT NULL,
  `CurrentBandwidth` INT NULL,
  `TotalStorage` INT NULL,
  `CurrentStorage` INT NULL,
  `EntityPower` VARCHAR(45) NULL DEFAULT 'Off',
  `EntityPool` VARCHAR(45) NULL DEFAULT 'Physical',
  `uri` VARCHAR(1024) NULL,
  `Threads` INT NULL,
  `CPU_OverAllocation` INT NULL DEFAULT 1,
  `RAM_OverAllocation` INT NULL DEFAULT 1,
  `Network_OverAllocation` INT NULL DEFAULT 1,
  `vCPU` INT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `comene_idx` (`tblEntities` ASC),
  CONSTRAINT `comene`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblServiceComputeResources`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblServiceComputeResources` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblComputeEntities` BIGINT UNSIGNED NULL,
  `tblServices` BIGINT UNSIGNED NULL,
  `CPU` BIGINT(20) NULL,
  `RAM` BIGINT(20) NULL,
  `Network` BIGINT(20) NULL,
  `iSCSI` BIGINT(20) NULL,
  `FC` BIGINT(20) NULL,
  `GHZ` BIGINT(20) NULL,
  `Power` TINYINT(3) NULL,
  `Pool` TINYINT(3) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `Compute_idx` (`tblComputeEntities` ASC),
  CONSTRAINT `Compute`
    FOREIGN KEY (`tblComputeEntities`)
    REFERENCES `CloudFlowPortal`.`tblComputeEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblServicesInterfaces`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblServicesInterfaces` (
  `id` BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT(20) UNSIGNED NULL COMMENT ' /* comment truncated */ /*Will be a VDC id*/',
  `BeginServiceEntityId` BIGINT UNSIGNED NULL,
  `BeginServicePortId` BIGINT NULL DEFAULT 0,
  `EndServiceEntityId` BIGINT UNSIGNED NULL,
  `EndServicePortId` BIGINT NULL DEFAULT 0,
  `InterfaceType` VARCHAR(45) NULL DEFAULT 'routed' COMMENT ' /* comment truncated */ /* routed  means normal interface; "transparent" means tap (copy) interface*/',
  `InterfaceIndex` INT NULL DEFAULT 0,
  `LineType` VARCHAR(50) NULL,
  `BeginPointX` VARCHAR(50) NULL,
  `BeginPointY` VARCHAR(50) NULL,
  `EndPointX` VARCHAR(50) NULL,
  `EndPointY` VARCHAR(50) NULL,
  `TurnPoint1X` VARCHAR(50) NULL,
  `TurnPoint1Y` VARCHAR(50) NULL,
  `TurnPoint2X` VARCHAR(50) NULL,
  `TurnPoint2Y` VARCHAR(50) NULL,
  `ZIndex` SMALLINT(6) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entityInterface_idx` (`tblEntities` ASC),
  CONSTRAINT `entityInterface`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblServiceNetworkResources`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblServiceNetworkResources` (
  `ResourceId` BIGINT(20) NOT NULL AUTO_INCREMENT,
  `EntityId` BIGINT(20) NOT NULL DEFAULT '0',
  `ServiceId` BIGINT(20) NOT NULL DEFAULT '0',
  `Throughput` BIGINT(20) NOT NULL DEFAULT '0',
  `Sessions` BIGINT(20) NOT NULL DEFAULT '0',
  `Users` BIGINT(20) NOT NULL DEFAULT '0',
  `Power` TINYINT(3) UNSIGNED NOT NULL DEFAULT '0',
  `Pool` TINYINT(3) UNSIGNED NOT NULL DEFAULT '0',
  PRIMARY KEY (`ResourceId`))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblServiceStorageResources`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblServiceStorageResources` (
  `ResourceId` BIGINT(20) NOT NULL AUTO_INCREMENT,
  `EntityId` BIGINT(20) NOT NULL DEFAULT '0',
  `ServiceId` BIGINT(20) NOT NULL DEFAULT '0',
  `Capacity` BIGINT(20) NOT NULL DEFAULT '0',
  `IOPS` BIGINT(20) NOT NULL DEFAULT '0',
  `Network` BIGINT(20) NOT NULL DEFAULT '0',
  `Power` TINYINT(3) UNSIGNED NOT NULL DEFAULT '0',
  `Pool` TINYINT(3) UNSIGNED NOT NULL DEFAULT '0',
  `Latency` INT(11) NOT NULL DEFAULT '0',
  PRIMARY KEY (`ResourceId`))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblServices`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblServices` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `ServiceType` VARCHAR(256) NULL DEFAULT 'Routed',
  `PhysicalDeviceFlag` TINYINT NULL DEFAULT 0 COMMENT ' /* comment truncated */ /*0 = Virtual device
*/',
  `UIType` VARCHAR(50) NULL,
  `PositionX` VARCHAR(50) NULL,
  `PositionY` VARCHAR(50) NULL,
  `RepeatDirection` VARCHAR(50) NULL,
  `ImagePath` VARCHAR(500) NULL,
  `ZIndex` SMALLINT(6) NULL,
  `HighAvailabilityOptions` VARCHAR(45) NULL DEFAULT 'Default',
  `HighAvailabilityOptionPolicy` VARCHAR(45) NULL DEFAULT 'VDC overrides device',
  `FirewallType` VARCHAR(45) NULL DEFAULT 'Routed',
  `LoadBalancerType` VARCHAR(45) NULL DEFAULT 'Routed',
  `SlicePreferencePolicy` VARCHAR(45) NULL DEFAULT 'VDC overrides device' COMMENT ' /* comment truncated */ /*Will be used only for VDC configuration*/',
  `Throughput` INT NULL DEFAULT 100 COMMENT ' /* comment truncated */ /*For VDC it will be a Enum Value , For Other Services it will be -1 for "Best Effort" and other values is for Accumulative*/',
  `BeginInstancesCount` SMALLINT NULL DEFAULT 1,
  `MaxInstancesCount` SMALLINT NULL DEFAULT 1,
  `ThroughputInc` INT NULL DEFAULT 100,
  `SharedExternalNetworkEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `DefaultGatewayEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `VPNType` SMALLINT(6) NULL COMMENT ' /* comment truncated */ /*For VPN use only*/',
  `EncryptionMethod` SMALLINT(6) NULL COMMENT ' /* comment truncated */ /*For VPN use only*/',
  `PKI` SMALLINT(6) NULL COMMENT ' /* comment truncated */ /*For VPN use only*/',
  `HashingAlgo` SMALLINT(6) NULL COMMENT ' /* comment truncated */ /*For VPN use only*/',
  `EncryptionAlgo` SMALLINT(6) NULL COMMENT ' /* comment truncated */ /*For VPN use only*/',
  `SSLProtocol` SMALLINT(6) NULL COMMENT ' /* comment truncated */ /*SSL Accelrator*/',
  `CipherProtocol` SMALLINT(6) NULL COMMENT ' /* comment truncated */ /*SSL ACCEL*/',
  `NoOfUsers` INT(11) NULL,
  `NoOfUsersInc` INT(11) NULL,
  `NoOfUsersMax` INT(11) NULL,
  `NoOfSessions` INT(11) NULL,
  `NoOfSessionsInc` INT(11) NULL,
  `NoOfSessionsMax` INT(11) NULL,
  `IPSIDS` VARCHAR(45) NULL DEFAULT 'IDS',
  `ServiceToServeID` BIGINT(20) NULL,
  `VLan` INT NULL DEFAULT 0,
  `VLanType` VARCHAR(45) NULL DEFAULT 'MAC-IN-MAC',
  `SubnetToMonitorID` BIGINT NULL DEFAULT 0,
  `IPSManagementServiceUniqueId` VARCHAR(64) NULL,
  `DefaultSliceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `DefaultSliceUniqueId` VARCHAR(45) NULL,
  `SelectedSliceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `SelectedSliceUniqueId` VARCHAR(45) NULL,
  `Qos` VARCHAR(45) NULL DEFAULT 'Default',
  `ServiceLevelAgreement` VARCHAR(45) NULL DEFAULT 'Default',
  `ServiceLevelAgreementPolicy` VARCHAR(45) NULL DEFAULT 'Default',
  `SharedExternalNetworkUniqueId` VARCHAR(45) NULL,
  `DefaultGateways` VARCHAR(2048) NULL DEFAULT '[{"name":"Default", "dbid":0}]',
  `nat_pat_mode` VARCHAR(45) NULL DEFAULT 'Disabled',
  `Throughputs` VARCHAR(128) NULL DEFAULT '',
  `DynOpBandwidth` TINYINT NULL DEFAULT 1 COMMENT ' /* comment truncated */ /*0 = Disabled; 1=Enabled*/',
  `DynOpCPU` TINYINT NULL DEFAULT 1,
  `DynOpRam` TINYINT NULL DEFAULT 1,
  `CPU_Red` INT NULL DEFAULT 75,
  `CPU_Green` INT NULL DEFAULT 60,
  `Throughtput_Red` INT NULL DEFAULT 80,
  `Throughput_Green` INT NULL DEFAULT 60,
  `RAM_Red` INT NULL DEFAULT 80,
  `RAM_Green` INT NULL DEFAULT 50,
  `CoolDown_up` INT NULL DEFAULT 90,
  `CoolDown_down` INT NULL DEFAULT 120,
  `lbs_mode` VARCHAR(45) NULL DEFAULT 'Layer 4',
  `northbound_port` VARCHAR(512) NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entityService_idx` (`tblEntities` ASC),
  CONSTRAINT `entityService`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblVDCTemplates`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblVDCTemplates` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `JSONString` LONGTEXT NULL DEFAULT NULL,
  `TemplateType` INT(11) NULL DEFAULT 0,
  `IsSecured` SMALLINT(6) NULL,
  `ImageSource` VARCHAR(200) NULL,
  `RecCreatedBy` VARCHAR(100) NULL,
  `RecCreatedDt` DATETIME NULL,
  `RecLastUpdateBy` VARCHAR(100) NULL,
  `RecLastUpdateDt` DATETIME NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entitytemplate_idx` (`tblEntities` ASC),
  CONSTRAINT `entitytemplate`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblVPNConnections`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblVPNConnections` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `PeerAddress` VARCHAR(512) NULL DEFAULT '0.0.0.0',
  `PeerSubnets` VARCHAR(512) NULL DEFAULT '0.0.0.0/0',
  `PeerID` VARCHAR(512) NULL DEFAULT 0,
  `AuthenticationMode` VARCHAR(100) NULL DEFAULT 'Preshared Key',
  `PSK` VARCHAR(100) NULL DEFAULT 'EnterPrivateKey',
  `Initiator` VARCHAR(100) NULL DEFAULT 'True',
  `DPDAction` VARCHAR(100) NULL DEFAULT 'None',
  `DPDInterval` INT NULL DEFAULT 20,
  `DPDTimeout` INT NULL DEFAULT 60,
  `P1IKEVersion` VARCHAR(100) NULL DEFAULT 'IKEv1',
  `P1IKEMode` VARCHAR(100) NULL DEFAULT 'Main',
  `P1PFS` VARCHAR(100) NULL DEFAULT 'Disabled',
  `P1Encryption` VARCHAR(100) NULL DEFAULT 'AES-128',
  `P1Authentication` VARCHAR(100) NULL DEFAULT 'SHA1',
  `P1SALifetime` INT NULL DEFAULT 3600,
  `P1KeepAlive` INT NULL DEFAULT 20,
  `P1NatTraversal` VARCHAR(100) NULL DEFAULT 'Disabled',
  `P2Encryption` VARCHAR(100) NULL DEFAULT 'AES-128',
  `P2Authentication` VARCHAR(100) NULL DEFAULT 'SHA1',
  `P2EncapsulationProtocol` VARCHAR(100) NULL DEFAULT 'Tunnel',
  `P2ActiveProtocol` VARCHAR(100) NULL DEFAULT 'ESP',
  `P2PFS` VARCHAR(100) NULL DEFAULT 'Disabled',
  `P2SALifetime` INT NULL DEFAULT 3600,
  `P2ReplayDetection` VARCHAR(100) NULL DEFAULT 'Disabled',
  `RemoteName` VARCHAR(512) NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entityvpnsvc_idx` (`tblEntities` ASC),
  CONSTRAINT `entityvpnsvc`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblContainerVolumes`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblContainerVolumes` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL COMMENT ' /* comment truncated */ /*Organization Id or Department Id*/',
  `VolumeClass` VARCHAR(64) NULL DEFAULT 'volume' COMMENT ' /* comment truncated */ /*volume, snapshot, backup, archive
*/',
  `Capacity` INT NULL DEFAULT 8,
  `StoragePriority` VARCHAR(100) NULL,
  `Permissions` VARCHAR(100) NULL DEFAULT 'All',
  `VolFormat` VARCHAR(100) NULL,
  `VolType` VARCHAR(100) NULL DEFAULT 'Block',
  `IQN` VARCHAR(100) NULL,
  `VolumePath` VARCHAR(1000) NULL DEFAULT '',
  `SnapshotPolicy` VARCHAR(100) NULL DEFAULT 'Disabled' COMMENT ' /* comment truncated */ /*disabled, enabled*/',
  `SnPolicyType` VARCHAR(500) NULL DEFAULT 'Recurring' COMMENT ' /* comment truncated */ /*recurring, fixed*/',
  `SnPolicyHrs` VARCHAR(500) NULL DEFAULT '',
  `SnPolicyLimit` INT NULL DEFAULT 0,
  `ArchivePolicy` VARCHAR(100) NULL DEFAULT 'Disabled' COMMENT ' /* comment truncated */ /*disabled, enabled*/',
  `ArPolicyType` VARCHAR(500) NULL DEFAULT 'Recurring',
  `ArPolicyWeekDays` VARCHAR(500) NULL DEFAULT '',
  `ArPolicyMonthDays` VARCHAR(500) NULL DEFAULT '',
  `ArPolicyTime` TIME NULL DEFAULT '00:00:00',
  `ArPolicyLimit` INT NULL DEFAULT 0,
  `ArContainerEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `BackupPolicy` VARCHAR(100) NULL DEFAULT 'Disabled',
  `BkPolicyType` VARCHAR(500) NULL DEFAULT 'Recurring',
  `BkPolicyWeekDays` VARCHAR(500) NULL DEFAULT '',
  `BkPolicyMonthDays` VARCHAR(500) NULL DEFAULT '',
  `BkPolicyTime` TIME NULL DEFAULT '00:00:00',
  `BkPolicyLimit` INT NULL DEFAULT 0,
  `BkContainerEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `UUID` VARCHAR(100) NULL,
  `created_at` DATETIME NULL,
  `created_by` VARCHAR(100) NULL,
  `BootServerEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `BootImageEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `tblFlavors` BIGINT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entityVolume_idx` (`tblEntities` ASC),
  CONSTRAINT `entityVolume`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblIP4Addresses`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblIP4Addresses` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `updated_at` TIMESTAMP NULL,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `IPAddress` VARCHAR(45) NULL,
  `IPMask` VARCHAR(45) NULL,
  `MacAddress` VARCHAR(45) NULL,
  `Network` VARCHAR(45) NULL,
  `name` VARCHAR(45) NULL,
  `uuid` VARCHAR(64) NULL,
  `subnet` VARCHAR(512) NULL,
  `service` VARCHAR(512) NULL,
  `server` VARCHAR(512) NULL,
  `vdc` VARCHAR(512) NULL,
  `department` VARCHAR(512) NULL,
  `organization` VARCHAR(512) NULL,
  `local_ip_address` VARCHAR(45) NULL,
  `serverfarm` VARCHAR(512) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `ip4entit_idx` (`tblEntities` ASC),
  CONSTRAINT `ip4entit`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblStorageEntities`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblStorageEntities` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `Uuid` VARCHAR(45) NULL,
  `Manufacturer` VARCHAR(256) NULL,
  `Model` VARCHAR(256) NULL,
  `TotalBandwidth` INT NULL DEFAULT 0,
  `AvailableBandwidth` INT NULL DEFAULT 0,
  `AllocationUnitBandwidth` INT NULL DEFAULT 0,
  `TotalStorage` INT NULL DEFAULT 0,
  `AvailableStorage` INT NULL DEFAULT 0,
  `AllocationUnitStorage` INT NULL DEFAULT 0,
  `TotalIOPS` INT NULL DEFAULT 0,
  `AvailableIOPS` INT NULL DEFAULT 0,
  `AllocationUnitIOPS` INT NULL DEFAULT 0,
  `EntityPower` VARCHAR(45) NULL DEFAULT 'Off',
  `EntityPool` VARCHAR(45) NULL DEFAULT 'Physical',
  `uri` VARCHAR(1024) NULL,
  `Latency-Quantitative` INT NULL DEFAULT 0,
  `Latency-Qualitative` VARCHAR(45) NULL DEFAULT 'Silver',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `pohystp_idx` (`tblEntities` ASC),
  CONSTRAINT `pohystp`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblNetworkEntities`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblNetworkEntities` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `Uuid` VARCHAR(45) NULL,
  `Manufacturer` VARCHAR(256) NULL,
  `Model` VARCHAR(256) NULL,
  `TotalBandwidth` INT NULL DEFAULT 0,
  `CurrentBandwidth` INT NULL DEFAULT 0,
  `TotalThroughput` INT NULL DEFAULT 0,
  `LicensedThroughput` INT NULL DEFAULT 0,
  `CurrentThroughput` INT NULL DEFAULT 0,
  `DeviceType` VARCHAR(45) NULL,
  `EntityPower` VARCHAR(45) NULL DEFAULT 'Off',
  `EntityPool` VARCHAR(45) NULL DEFAULT 'Physical',
  `DeviceFunction` VARCHAR(45) NULL,
  `uri` VARCHAR(1024) NULL,
  `Throughputs` VARCHAR(128) NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `phyne_idx` (`tblEntities` ASC),
  CONSTRAINT `phyne`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblPortEntities`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblPortEntities` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `updated_at` TIMESTAMP NULL,
  `tblEntities` BIGINT UNSIGNED NULL,
  `Name` VARCHAR(500) NULL,
  `Description` VARCHAR(500) NULL,
  `EntityStatus` VARCHAR(300) NULL,
  `Uuid` VARCHAR(64) NULL,
  `TotalBandwidth` INT NULL DEFAULT 0,
  `CurrentBandwidth` INT NULL DEFAULT 0,
  `MacAddress` VARCHAR(45) NULL DEFAULT '',
  `ConnectedWithDevice` VARCHAR(45) NULL,
  `ConnectedWithDeviceType` VARCHAR(45) NULL,
  `ConnectedWithDevicePort` VARCHAR(45) NULL,
  `uri` VARCHAR(1024) NULL,
  `network` VARCHAR(45) NULL,
  `ip_address` VARCHAR(45) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `portket_idx` (`tblEntities` ASC),
  CONSTRAINT `portket`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblExternalClouds`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblExternalClouds` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `created_at` TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NULL,
  `deleted_at` TIMESTAMP NULL,
  `deleted` TINYINT NULL DEFAULT 0,
  `password` VARCHAR(500) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblResourcesCompute`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblResourcesCompute` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `updated_at` TIMESTAMP NULL,
  `tblEntities` BIGINT UNSIGNED NULL,
  `Catagory` VARCHAR(45) NULL COMMENT ' /* comment truncated */ /*allocated or deployed*/',
  `TypeTitle` VARCHAR(45) NULL,
  `Type` VARCHAR(45) NULL,
  `CPU` BIGINT(20) NULL DEFAULT 0,
  `RAM` BIGINT(20) NULL DEFAULT 0,
  `Network` BIGINT(20) NULL DEFAULT 0,
  `SliceId` BIGINT NULL DEFAULT 0,
  `ParentEntityId` BIGINT NULL DEFAULT 0,
  `EntityType` VARCHAR(45) NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `Entity_idx` (`tblEntities` ASC),
  CONSTRAINT `ComputeLink`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblResourcesStorage`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblResourcesStorage` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `updated_at` TIMESTAMP NULL,
  `tblEntities` BIGINT UNSIGNED NULL,
  `Catagory` VARCHAR(45) NULL COMMENT ' /* comment truncated */ /*allocated or deployed*/',
  `TypeTitle` VARCHAR(45) NULL,
  `Type` VARCHAR(45) NULL,
  `Capacity` INT NULL DEFAULT 0,
  `IOPS` INT NULL DEFAULT 0,
  `Network` INT NULL DEFAULT 0,
  `SliceId` BIGINT NULL DEFAULT 0,
  `ParentEntityId` BIGINT NULL DEFAULT 0,
  `EntityType` VARCHAR(45) NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `Entity_idx` (`tblEntities` ASC),
  CONSTRAINT `StorageLink`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblResourcesNetwork`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblResourcesNetwork` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `updated_at` TIMESTAMP NULL,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `Catagory` VARCHAR(45) NULL COMMENT ' /* comment truncated */ /*allocated or deployed*/',
  `TypeTitle` VARCHAR(45) NULL,
  `Type` VARCHAR(45) NULL,
  `Throughput` INT NULL DEFAULT 0,
  `Sessions` INT NULL DEFAULT 0,
  `Users` INT NULL DEFAULT 0,
  `SliceId` BIGINT NULL DEFAULT 0,
  `ParentEntityId` BIGINT NULL DEFAULT 0,
  `EntityType` VARCHAR(45) NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `Entity_idx` (`tblEntities` ASC),
  CONSTRAINT `NetworkLink`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblVdcs`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblVdcs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NOT NULL,
  `DefaultSliceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `SelectedSliceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `uri` VARCHAR(1024) NULL,
  `VDCPerformancePolicy` VARCHAR(45) NULL DEFAULT 'Default',
  `SlicePreferencePolicy` VARCHAR(45) NULL DEFAULT 'VDC overrides device' COMMENT ' /* comment truncated */ /*Will be used only for VDC configuration*/',
  `HighAvailabilityOptions` VARCHAR(45) NULL DEFAULT 'Default',
  `HighAvailabilityOptionPolicy` VARCHAR(45) NULL DEFAULT 'VDC overrides device',
  `Administrator` VARCHAR(500) NULL,
  `Email` VARCHAR(500) NULL,
  `Location` VARCHAR(500) NULL,
  `showCanvasGrid` TINYINT NULL DEFAULT 0,
  `activated_at` DATETIME NULL,
  `last_log_time` DATETIME NULL,
  `zoom` FLOAT NULL DEFAULT 0,
  `LastResyncTime` DATETIME NULL,
  `HawkResyncTime` DATETIME NULL,
  `ResyncIntervalSeconds` INT NULL DEFAULT 30,
  PRIMARY KEY (`id`),
  INDEX `FK_tblVdcs_tblEntities` (`tblEntities` ASC),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  CONSTRAINT `FK_tblVdcs_tblEntities`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblSystem`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblSystem` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `UpdateSystemRequestTime` DATETIME NULL,
  `UpdateSystemRequested` TINYINT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  INDEX `FK_tblSystem_tblEntities` (`tblEntities` ASC),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  CONSTRAINT `FK_tblSystem_tblEntities`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblUris`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblUris` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `created_at` TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NULL,
  `deleted_at` TIMESTAMP NULL,
  `deleted` TINYINT NULL DEFAULT 0,
  `tblSlices` BIGINT UNSIGNED NULL DEFAULT 0,
  `tblTableName` VARCHAR(45) NULL,
  `tblTableId` BIGINT UNSIGNED NULL DEFAULT 0,
  `type` VARCHAR(45) NULL,
  `uri` VARCHAR(1024) NULL COMMENT ' /* comment truncated */ /*URI where slice address must be appended*/',
  `statistics` VARCHAR(1024) NULL,
  `statistics_time` DATETIME NULL,
  `rest_response` TEXT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `uriEntitie_idx` (`tblEntities` ASC),
  CONSTRAINT `uriEntitie`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblJobsQueue`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblJobsQueue` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `Progress` INT NULL DEFAULT 0,
  `Command` VARCHAR(1024) NULL,
  `Response` VARCHAR(1024) NULL,
  `JobServiceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `JobServiceName` VARCHAR(45) NULL,
  `Status` VARCHAR(45) NULL,
  `PrimaryJobEntityId` BIGINT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entitiesPending_idx` (`tblEntities` ASC),
  CONSTRAINT `entitiesPending`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblEntitiesACL`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblEntitiesACL` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `AclRole` VARCHAR(45) NULL COMMENT ' /* comment truncated */ /*IT, Organization, Department, VDC*/',
  `AclEntityId` BIGINT UNSIGNED NULL DEFAULT 0 COMMENT ' /* comment truncated */ /*Point to system entity for IT; organization entity for organization; one or more departments for department;  one for more VDCs for VDC*/',
  `ContainerEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `rbackentity_idx` (`tblEntities` ASC),
  CONSTRAINT `rbackentity`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblLogs`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblLogs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `ParentEntityId` BIGINT UNSIGNED NULL,
  `created_at` DATETIME NULL,
  `unique_id` BIGINT NULL DEFAULT 0,
  `Source` VARCHAR(45) NULL DEFAULT 'Hawk',
  `Field` VARCHAR(45) NULL DEFAULT 'Info',
  `Hint` VARCHAR(45) NULL,
  `Message` MEDIUMTEXT NULL,
  `Severity` INT NULL DEFAULT 0,
  `Commandid` VARCHAR(45) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `messageentit_idx` (`tblEntities` ASC),
  CONSTRAINT `messageentit`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblVirtualNetworks`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblVirtualNetworks` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `NetworkType` VARCHAR(100) NULL,
  `Throughput` INT NULL DEFAULT 0,
  `IPAddress` VARCHAR(45) NULL,
  `IPMask` VARCHAR(45) NULL,
  `BeginInstancesCount` SMALLINT NULL DEFAULT 1,
  `MaxInstancesCount` SMALLINT NULL DEFAULT 1,
  `ThroughputInc` INT NULL DEFAULT 100,
  `Topology` VARCHAR(45) NULL DEFAULT 'Star',
  `Throughputs` VARCHAR(128) NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  INDEX `entitiesNetwork_idx` (`tblEntities` ASC),
  CONSTRAINT `entitiesNetwork`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblNetworkStatistics`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblNetworkStatistics` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `tblServicePorts` BIGINT UNSIGNED NULL DEFAULT 0,
  `subnet` VARCHAR(45) NULL,
  `timestamp` DATETIME NULL,
  `txFrameCount` BIGINT NULL DEFAULT 0,
  `rxFrameCount` BIGINT NULL DEFAULT 0,
  `txByteCount` BIGINT NULL DEFAULT 0,
  `rxByteCount` BIGINT NULL DEFAULT 0,
  `txErrorCount` BIGINT NULL DEFAULT 0,
  `rxErrorCount` BIGINT NULL DEFAULT 0,
  `rxDropCount` BIGINT NULL DEFAULT 0,
  `txDropCount` BIGINT NULL DEFAULT 0,
  `rxCongestionCount` BIGINT NULL DEFAULT 0,
  `txCongestionCount` BIGINT NULL DEFAULT 0,
  `txBitsPerSec` BIGINT NULL DEFAULT 0,
  `rxBitsPerSec` BIGINT NULL DEFAULT 0,
  `rxFrameCountPerSec` BIGINT NULL DEFAULT 0,
  `txFrameCountPerSec` BIGINT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `portstats_idx` (`tblEntities` ASC),
  CONSTRAINT `portnetstats`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblComputeStatistics`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblComputeStatistics` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `created_at` TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  `timestamp` DATETIME NULL,
  `vcpus` TINYINT NULL DEFAULT 0,
  `state` VARCHAR(45) NULL DEFAULT '',
  `cpu_utilization_percentage` DECIMAL(5,2) NULL DEFAULT 0,
  `memory_utilization_percentage` DECIMAL(5,2) NULL DEFAULT 0,
  `current_memory` BIGINT NULL DEFAULT 0,
  `current_cpu` BIGINT NULL DEFAULT 0,
  `throughput` BIGINT NULL DEFAULT 0,
  `throughput_percentage` DECIMAL(5,2) NULL DEFAULT 0,
  `latency_average` BIGINT NULL DEFAULT 0,
  `storage_bandwidth` BIGINT NULL DEFAULT 0,
  `cputime` BIGINT NULL DEFAULT 0,
  `memory_allocated` BIGINT NULL DEFAULT 0,
  `element_count` INT NULL DEFAULT 1,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `comstats_idx` (`tblEntities` ASC),
  CONSTRAINT `comstats`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblStorageStatistics`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblStorageStatistics` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `timestamp` DATETIME NULL,
  `name` VARCHAR(45) NULL DEFAULT '',
  `ReadRequests` BIGINT NULL DEFAULT 0,
  `ReadBytes` BIGINT NULL DEFAULT 0,
  `ReadBytesPerSec` BIGINT NULL DEFAULT 0,
  `WriteBytesPerSec` BIGINT NULL DEFAULT 0,
  `ReadRequestsPerSec` BIGINT NULL DEFAULT 0,
  `WriteRequestsPerSec` BIGINT NULL DEFAULT 0,
  `WriteLatency` BIGINT NULL DEFAULT 0,
  `FlushRequests` BIGINT NULL DEFAULT 0,
  `FlushRequestsPerSec` BIGINT NULL DEFAULT 0,
  `WriteRequests` BIGINT NULL DEFAULT 0,
  `ReadLatency` BIGINT NULL DEFAULT 0,
  `FlushLatency` BIGINT NULL DEFAULT 0,
  `WriteBytes` BIGINT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `storstats_idx` (`tblEntities` ASC),
  CONSTRAINT `storstats`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblServiceStatistics`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblServiceStatistics` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `timestamp` DATETIME NULL,
  `memory_utilization_pct` DECIMAL(5,2) NULL DEFAULT 0,
  `cpu_utilization_pct` DECIMAL(5,2) NULL DEFAULT 0,
  `throughput_pct` DECIMAL(5,2) NULL DEFAULT 0,
  `throughput` BIGINT NULL DEFAULT 0,
  `latency_average` BIGINT NULL DEFAULT 0,
  `storage_bandwidth` BIGINT NULL DEFAULT 0,
  `all_svc_updated_flag` TINYINT NULL DEFAULT 0 COMMENT ' /* comment truncated */ /*This is an average of service and cloned servces  nodes */',
  `all_svc_mem_pct` DECIMAL(5,2) NULL DEFAULT 0,
  `all_svc_cpu_pct` DECIMAL(5,2) NULL DEFAULT 0,
  `all_svc_thru_pct` DECIMAL(5,2) NULL DEFAULT 0,
  `svc_add_remove_flag` TINYINT NULL DEFAULT 0 COMMENT ' /* comment truncated */ /*0 = nothing done; 1= added a new service ; 2= removed a service*/',
  `all_svc_thru` BIGINT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `svcstats_idx` (`tblEntities` ASC),
  CONSTRAINT `svcstats`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblVdcProvisionLogs`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblVdcProvisionLogs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `created_at` DATETIME NULL,
  `LogType` VARCHAR(45) NULL,
  `Message` MEDIUMTEXT NULL,
  `Serverity` INT NULL DEFAULT 0,
  `Commandid` VARCHAR(45) NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `messageentit_idx` (`tblEntities` ASC),
  CONSTRAINT `vdcsttatus`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblWidgets`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblWidgets` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `ServiceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `PortEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `ChildEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `GrandchildEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `widget_pos` TINYINT NULL DEFAULT 0,
  `widget_order` TINYINT NULL DEFAULT 0,
  `granularity` INT NULL DEFAULT 20,
  PRIMARY KEY (`id`),
  INDEX `FK_tblWidgets_tblEntities` (`tblEntities` ASC),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  CONSTRAINT `FK_tblWidgets_tblEntities`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblAPILogs`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblAPILogs` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `created_at` TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  `elapsed_time` INT NULL DEFAULT 0,
  `user_id` BIGINT NULL DEFAULT 0,
  `entity` VARCHAR(45) NULL,
  `dbid` BIGINT NULL DEFAULT 0,
  `function` VARCHAR(45) NULL,
  `options` TEXT NULL,
  `response` TEXT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC))
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblEntityDetails`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblEntityDetails` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `created_at` TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NULL,
  `deleted_at` TIMESTAMP NULL,
  `deleted` TINYINT NULL DEFAULT 0,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `type` VARCHAR(45) NULL DEFAULT 'default',
  `details` TEXT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `uriEntitie_idx` (`tblEntities` ASC),
  CONSTRAINT `uriDetails`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblInterfaceVertices`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblInterfaceVertices` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `positionX` INT NULL,
  `positionY` INT NULL,
  `vertexorder` INT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entitytemplate_idx` (`tblEntities` ASC),
  CONSTRAINT `interfacevertex`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblAttachedEntitiesStatus`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblAttachedEntitiesStatus` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `VdcEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `ChildEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `GroupEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `ServiceEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `PortEntityId` BIGINT UNSIGNED NULL DEFAULT 0,
  `EntityStatus` VARCHAR(300) NULL DEFAULT 'Ready',
  `details` TEXT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `entitybridge_idx` (`VdcEntityId` ASC),
  CONSTRAINT `entitybridge`
    FOREIGN KEY (`VdcEntityId`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblSSHPublicKeys`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblSSHPublicKeys` (
  `id` BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `name` VARCHAR(255) NULL,
  `fingerprint` VARCHAR(255) NULL,
  `public_key` MEDIUMTEXT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  INDEX `entity_KV_idx` (`tblEntities` ASC),
  CONSTRAINT `entity_pss`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblEntityPolicies`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblEntityPolicies` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `Policy` TEXT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `rbackentity_idx` (`tblEntities` ASC),
  CONSTRAINT `entitypolicies`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblUserData`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblUserData` (
  `id` BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `User_Data` LONGTEXT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  INDEX `entity_KV_idx` (`tblEntities` ASC),
  CONSTRAINT `entity_user_data`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblFlavors`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblFlavors` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `description` VARCHAR(500) NULL DEFAULT '',
  `name` VARCHAR(500) NULL DEFAULT '',
  `cpu` INT NULL DEFAULT 0,
  `memory` INT NULL DEFAULT 0,
  `storage` INT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  INDEX `FK_tblFlavors_tblEntities` (`tblEntities` ASC),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  CONSTRAINT `FK_tblFlavors_tblEntities`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblResourcesFlavors`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblResourcesFlavors` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `updated_at` TIMESTAMP NULL,
  `tblEntities` BIGINT UNSIGNED NULL,
  `tblFlavors` BIGINT UNSIGNED NULL DEFAULT 0 COMMENT ' /* comment truncated */ /*allocated or deployed*/',
  `Catagory` VARCHAR(45) NULL COMMENT ' /* comment truncated */ /*allocated or deployed*/',
  `TypeTitle` VARCHAR(45) NULL,
  `Type` VARCHAR(45) NULL,
  `Quantity` BIGINT(20) NULL DEFAULT 0,
  `SliceId` BIGINT NULL DEFAULT 0,
  `ParentEntityId` BIGINT NULL DEFAULT 0,
  `EntityType` VARCHAR(45) NULL DEFAULT '',
  PRIMARY KEY (`id`),
  UNIQUE INDEX `id_UNIQUE` (`id` ASC),
  INDEX `Entity_idx` (`tblEntities` ASC),
  CONSTRAINT `flavorLink`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblConsoleLog`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblConsoleLog` (
  `id` BIGINT(20) UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL,
  `console_log` LONGTEXT NULL,
  PRIMARY KEY (`id`),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  INDEX `entity_KV_idx` (`tblEntities` ASC),
  CONSTRAINT `entty_console_log`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


-- -----------------------------------------------------
-- Table `CloudFlowPortal`.`tblImageLibrary`
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS `CloudFlowPortal`.`tblImageLibrary` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `tblEntities` BIGINT UNSIGNED NULL DEFAULT 0,
  `created_by` VARCHAR(45) NULL DEFAULT 'user',
  PRIMARY KEY (`id`),
  INDEX `FK_tblImageLibrary_tblEntities` (`tblEntities` ASC),
  UNIQUE INDEX `Id_UNIQUE` (`id` ASC),
  CONSTRAINT `FK_tblImageLibrary_tblEntities`
    FOREIGN KEY (`tblEntities`)
    REFERENCES `CloudFlowPortal`.`tblEntities` (`id`)
    ON DELETE CASCADE
    ON UPDATE NO ACTION)
ENGINE = InnoDB;


SET SQL_MODE=@OLD_SQL_MODE;
SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS;
SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS;
