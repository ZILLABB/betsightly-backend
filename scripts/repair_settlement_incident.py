import argparse,json,sys
from leagues.settlement_incident_repair import run,CONFIRM_TOKEN,RepairPreconditionError
def main():
 p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--confirm',default='');p.add_argument('--backup-dir',default='maintenance_backups');p.add_argument('--verify',action='store_true');a=p.parse_args()
 if a.apply and a.verify:p.error('--apply and --verify cannot be combined')
 try:r=run(apply=a.apply,confirmation=a.confirm,backup_dir=a.backup_dir,verify=a.verify)
 except RepairPreconditionError as e: print(json.dumps({'status':'refused','reason':str(e)}));return 2
 print(json.dumps(r,indent=2,default=str));return 0 if not a.verify or r['verification_clean'] else 3
if __name__=='__main__':sys.exit(main())
