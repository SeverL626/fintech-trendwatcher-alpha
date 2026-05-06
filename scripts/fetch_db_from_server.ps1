$ErrorActionPreference = "Stop"

$KeyPath = "C:\Users\alexl\.ssh\alex_vps"
$RemoteDb = "fastuser@159.253.20.240:/opt/myapp/data/app.db"
$Destination = "C:\Users\alexl\Downloads\app.db"

Write-Host "Downloading production database from $RemoteDb"
Write-Host "Destination: $Destination"

scp -i $KeyPath $RemoteDb $Destination

Write-Host "Database downloaded successfully."
