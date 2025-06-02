@echo off
echo Deploying to Railway...
git add .
git commit -m "Railway minimal deployment - Python 3.12 compatible"
git push origin dev
echo Done! Check Railway dashboard for deployment status.
