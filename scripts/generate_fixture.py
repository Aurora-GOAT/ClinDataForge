import argparse, json
from clinforge.synthetic import save_dataset
p=argparse.ArgumentParser()
p.add_argument('--out',default='examples/generated_fixture')
p.add_argument('--n',type=int,default=600)
p.add_argument('--seed',type=int,default=20261025)
a=p.parse_args()
print(json.dumps(save_dataset(a.out,a.n,a.seed),ensure_ascii=False,indent=2))
