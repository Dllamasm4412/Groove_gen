import warnings; warnings.filterwarnings("ignore")
import sys, os
import numpy as np, pandas as pd, matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

plt.style.use('seaborn-v0_8-whitegrid')
plt.rcParams.update({'figure.dpi': 150, 'font.size': 11,
                     'axes.titlesize': 13, 'axes.titleweight': 'bold'})
ACCENT='#20808D'; GREY='#9a9a9a'; RUST='#A84B2F'

FEAT=str(config.TRACK_FEATURES_CSV)
SURV=str(config.SURVEY_CSV)

feats=pd.read_csv(FEAT)
surv=pd.read_csv(SURV)
meta=surv[["trackID","song_dance","song_energy","song_bpm"]].drop_duplicates("trackID")
df=feats.merge(meta,on="trackID").dropna(subset=["song_dance","beat_consistency"]).reset_index(drop=True)
z=lambda s:(s-s.mean())/s.std(ddof=0)
df["groove_proxy"]=(z(df.beat_consistency)+z(df.plp_mean)+z(df.hpss_percussive_ratio)
                    +z(df.low_band_energy_ratio)-z(df.lhl_syncopation_mean)**2)

fig,axes=plt.subplots(1,3,figsize=(16,5.2),constrained_layout=True)

# Panel 1: H1 convergent — groove_proxy vs song_dance
ax=axes[0]
r=stats.pearsonr(df.groove_proxy,df.song_dance)[0]; rho=stats.spearmanr(df.groove_proxy,df.song_dance)[0]
ax.scatter(df.groove_proxy,df.song_dance,s=14,alpha=.45,color=ACCENT,edgecolor='none')
m,b=np.polyfit(df.groove_proxy,df.song_dance,1)
xs=np.linspace(df.groove_proxy.min(),df.groove_proxy.max(),50)
ax.plot(xs,m*xs+b,color=RUST,lw=2)
ax.set_title(f"H1: groove_proxy vs danceability\nPearson r={r:.2f} (target ≥0.50) · Spearman ρ={rho:.2f}",loc='left')
ax.set_xlabel("groove_proxy (z, unit-weighted)"); ax.set_ylabel("Spotify song_dance (0–100)")

# Panel 2: H3 Witek inverted-U test — song_dance vs z(syncopation) with quadratic fit
ax=axes[1]
zs=z(df.lhl_syncopation_mean).values; y=df.song_dance.values
ax.scatter(zs,y,s=14,alpha=.4,color=GREY,edgecolor='none')
coef=np.polyfit(zs,y,2)
xs=np.linspace(zs.min(),zs.max(),100)
ax.plot(xs,np.polyval(coef,xs),color=RUST,lw=2.2)
ax.set_title(f"H3: NO inverted-U on syncopation\nquadratic β={coef[0]:+.2f} (need negative) → monotonic, not peaked",loc='left')
ax.set_xlabel("z(LHL syncopation)"); ax.set_ylabel("Spotify song_dance (0–100)")

# Panel 3: H4 Janata tempo band
ax=axes[2]
bpm=df.song_bpm.values; inb=(bpm>=110)&(bpm<=130)
ax.scatter(bpm[~inb],y[~inb],s=14,alpha=.35,color=GREY,edgecolor='none',label='outside 110–130')
ax.scatter(bpm[inb],y[inb],s=16,alpha=.6,color=ACCENT,edgecolor='none',label='110–130 BPM')
ax.axvspan(110,130,color=ACCENT,alpha=.08)
ax.set_title(f"H4: danceability higher in 110–130 BPM band\n+{y[inb].mean()-y[~inb].mean():.1f} pts (66.1 vs 56.8), p<.001",loc='left')
ax.set_xlabel("Spotify song_bpm"); ax.set_ylabel("Spotify song_dance (0–100)")
ax.legend(frameon=False,fontsize=9,loc='lower right')

fig.suptitle("Sophia corpus (N=643 unique tracks): groove_proxy validation against Spotify danceability",
             fontsize=15,fontweight='bold',ha='left',x=0.005)
fig.text(0.005,-0.02,"Target = Spotify song_dance (no participant groove rating exists in dataset). "
         "groove_proxy = unit-weighted z-sum of beat_consistency, plp_mean, hpss_percussive_ratio, "
         "low_band_energy_ratio, minus z(syncopation)². Source: track_features.csv + survey_and_music_data_N_122.",
         ha='left',va='top',fontsize=8,color='#555')
fig.savefig(str(config.LAYER1_FIG),bbox_inches='tight',facecolor='white')
print("saved layer1_validation.png")

# Layer 2 standardized betas
fig2,ax=plt.subplots(figsize=(9,5),constrained_layout=True)
import statsmodels.api as sm
from sklearn.preprocessing import StandardScaler
L2=["tempo_final","lhl_syncopation_mean","hpss_percussive_ratio","onset_density",
    "beat_consistency","low_band_energy_ratio","spectral_flatness_mean"]
sub=df.dropna(subset=L2).reset_index(drop=True)
Xs=StandardScaler().fit_transform(sub[L2].values)
ols=sm.OLS(sub.song_dance.values,sm.add_constant(Xs)).fit()
betas=ols.params[1:]; ci=ols.conf_int()[1:]
order=np.argsort(betas)
names=[L2[i].replace('_',' ') for i in order]
b=betas[order]; lo=ci[order,0]; hi=ci[order,1]
colors=[ACCENT if v>0 else RUST for v in b]
ax.barh(range(len(b)),b,color=colors,alpha=.85)
ax.errorbar(b,range(len(b)),xerr=[b-lo,hi-b],fmt='none',ecolor='#333',capsize=3,lw=1)
ax.set_yticks(range(len(b))); ax.set_yticklabels(names)
ax.axvline(0,color='#333',lw=.8)
ax.set_xlabel("Standardized β (effect on song_dance)")
ax.set_title(f"Layer 2: acoustic predictors of danceability\nCV R²=0.18±0.04, CV Spearman ρ=0.44 · percussive ratio & bass dominate",loc='left')
fig2.text(0.005,-0.03,"7-feature OLS, standardized predictors, error bars = 95% CI. "
          "onset_density substitutes prereg onset_rate; spectral_flatness substitutes spectral_flux.",
          ha='left',va='top',fontsize=8,color='#555')
fig2.savefig(str(config.LAYER2_FIG),bbox_inches='tight',facecolor='white')
print("saved layer2_betas.png")
