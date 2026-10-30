# T1530 Data from Cloud Storage

## What it looks like
An identity reads many objects from a cloud storage bucket in a short burst.

## Signals that point to malicious
- Sensitive bucket (for example finance-reports) read by a scripted client such as python-requests.
- Same source IP as a suspicious sign-in.
- Part of a sequence after discovery activity.

## Signals that point to benign
- Approved export with a change ticket, using a normal client such as Excel.
- Known backup service accounts on schedule.

## Triage guidance
Check the client user agent, the source IP and whether a change record exists.
