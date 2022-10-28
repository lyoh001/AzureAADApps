# VICGOV - Azure Active Directory Apps Secret Expiry Date Report
## 1. Introduction
### 1.1	Overview

A number of challenges arise when managing AAD apps across multiple tenants, Hosting Services team have been working to make this process easier to maintain with less administrative overhead.

This document is intended to provide a high level overview of workflow on how the automation notifies the admins with Azure AD apps secret expiry dates in VICGOV.

Included in this report is a step by step detailed guide around where to look for troubleshooting.

## 2 Incident
- Description: The customer has been experiencing Azure DevOps pipeline failures due to expiring client/object IDs hence seeking help from Cenitex to provide with the list of client/objectIds and the related applicationTemplateIds for both Nonprod and Prod subscription in terms of their expiry dates so we can plan the renewals accordingly.
This issue happened in the past incident
The solution should contain:
service principal tokens along with app ID's & Object ID's in an excel sheet for Prod and Non-Prod accounts.
- Owners: Tier 0

## 3 Logical Architecture
### 3.1	Logical System Component Overview
![Figure 1: Logical Architecture Overview](./images/workflow.png)
1. Scheduled Job @ 7am on Friday.
2. Function retreives the secrets from the Keyvault.
3. Queries AAD for validating managed identity.
4. Checks AAD for the apps secret expiry dates for targeted subscriptions.
5. The notification email gets sent via logic apps with the report attached.
