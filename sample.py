import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches

def bond_price(face_value, coupon_rate, maturity, yield_to_maturity, freq=2):
    periods = int(maturity * freq)
    coupon = (coupon_rate / freq) * face_value
    ytm = yield_to_maturity / freq
    times = np.arange(1, periods + 1)
    pv_coupons = coupon / (1 + ytm) ** times
    pv_face = face_value / (1 + ytm) ** periods
    price = np.sum(pv_coupons) + pv_face
    return price

def macaulay_duration(face_value, coupon_rate, maturity, yield_to_maturity, freq=2):
    periods = int(maturity * freq)
    coupon = (coupon_rate / freq) * face_value
    ytm = yield_to_maturity / freq
    times = np.arange(1, periods + 1)
    pv_coupons = coupon * times / (1 + ytm) ** times
    pv_face = face_value * periods / (1 + ytm) ** periods
    weighted_cash_flows = np.sum(pv_coupons) + pv_face
    price = bond_price(face_value, coupon_rate, maturity, yield_to_maturity, freq)
    duration = weighted_cash_flows / price
    return duration / freq

# Parameters
face_value = 1000
maturity = 30
coupon_rates = [0.0, 0.03, 0.06]
yields = np.linspace(0.01, 0.15, 100)

# Set style for better visualization

colors = ['#FF9999', '#66B2FF', '#99FF99']

# Plot 1: Bond Price vs. Yield
fig, ax = plt.subplots(figsize=(12, 7))

for idx, coupon_rate in enumerate(coupon_rates):
    prices = [bond_price(face_value, coupon_rate, maturity, y) for y in yields]
    ax.plot(yields * 100, prices, label=f'Coupon Rate = {coupon_rate * 100}%', 
            color=colors[idx], linewidth=2.5)
    
    # Add par value line and annotation
    ax.axhline(y=face_value, color='gray', linestyle='--', alpha=0.5)
    ax.text(1, face_value * 1.02, 'Par Value ($1000)', 
            fontsize=10, color='gray')

# Highlight premium and discount regions
ax.fill_between(yields * 100, face_value, 2000, alpha=0.1, color='green', 
                label='Premium Bond Region')
ax.fill_between(yields * 100, 0, face_value, alpha=0.1, color='red', 
                label='Discount Bond Region')

ax.set_title('Bond Price vs. Yield to Maturity\n30-Year Bonds with Different Coupon Rates', 
             fontsize=14, pad=20)
ax.set_xlabel('Yield to Maturity (%)', fontsize=12)
ax.set_ylabel('Bond Price ($)', fontsize=12)
ax.legend(loc='upper right', frameon=True)
ax.grid(True, alpha=0.3)

# Add annotations explaining key concepts
ax.annotate('Higher price sensitivity\nfor zero-coupon bonds', 
            xy=(7, 1400), xytext=(9, 1600),
            arrowprops=dict(facecolor='black', shrink=0.05),
            bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.3))

plt.tight_layout()
plt.show()

# Plot 2: Duration Analysis
fig, ax = plt.subplots(figsize=(12, 7))

for idx, coupon_rate in enumerate(coupon_rates):
    durations = [macaulay_duration(face_value, coupon_rate, maturity, y) 
                 for y in yields]
    ax.plot(yields * 100, durations, label=f'Coupon Rate = {coupon_rate * 100}%', 
            color=colors[idx], linewidth=2.5)

ax.set_title('Macaulay Duration vs. Yield to Maturity\nImpact of Coupon Rates on Interest Rate Risk',
             fontsize=14, pad=20)
ax.set_xlabel('Yield to Maturity (%)', fontsize=12)
ax.set_ylabel('Duration (Years)', fontsize=12)
ax.legend(loc='upper right', frameon=True)
ax.grid(True, alpha=0.3)

# Add annotation explaining duration concept
ax.annotate('Lower duration = Lower interest rate risk', 
            xy=(10, 15), xytext=(11, 18),
            arrowprops=dict(facecolor='black', shrink=0.05),
            bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.3))

plt.tight_layout()
plt.show()

# Plot 3: Maturity Comparison
fig, ax = plt.subplots(figsize=(12, 7))

maturities = [10, 20, 30]
coupon_rate = 0.05

for idx, maturity in enumerate(maturities):
    durations = [macaulay_duration(face_value, coupon_rate, maturity, y) 
                 for y in yields]
    ax.plot(yields * 100, durations, 
            label=f'Maturity = {maturity} Years', 
            color=colors[idx], linewidth=2.5)

ax.set_title('Impact of Maturity on Duration\n5% Coupon Bonds with Different Maturities',
             fontsize=14, pad=20)
ax.set_xlabel('Yield to Maturity (%)', fontsize=12)
ax.set_ylabel('Duration (Years)', fontsize=12)
ax.legend(loc='upper right', frameon=True)
ax.grid(True, alpha=0.3)

# Add annotation about maturity impact
ax.annotate('Longer maturity = Higher interest rate risk', 
            xy=(5, 20), xytext=(6, 23),
            arrowprops=dict(facecolor='black', shrink=0.05),
            bbox=dict(boxstyle='round,pad=0.5', fc='yellow', alpha=0.3))

plt.tight_layout()
plt.show()