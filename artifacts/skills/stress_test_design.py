from keystone.models import sustainability as s
fam = s.Family(**FAMILY)
d = s.Design(**DESIGN)
base = s.simulate(fam, s.Home(), d, n_paths=1500)
risky = s.Family(**{**FAMILY, "income_volatility": FAMILY.get("income_volatility", 1.0) * 1.5})
a = dict(s.ASSUMPTIONS, insurance_shock_prob=0.15)
stressed = s.simulate(risky, s.Home(), d, n_paths=1500, a=a)
print(f"base {base['p_sustained_10y']:.1%} -> stressed {stressed['p_sustained_10y']:.1%} (job loss x1.5, insurance shock p=15%/yr)")
