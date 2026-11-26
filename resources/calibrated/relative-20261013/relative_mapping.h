/* Relative calibration candidate. Generated from audited October 2026
 * games. No human anchor. Continuous inverse, restricted to 600--2600. */
static double gui_relative_internal_setting(double requested) {
    static const double strength[] = {577.40273357835656,733.93147958166674,919.72004182331909,1004.2227082648424,1124.3436719486162,1276.7359061676971,1373.9412644798497,1500,1727.633293754481,1924.3911749604852,2061.6786009714569,2138.4556157097286,2226.1676144297985,2345.0207362738943,2636.935789612694};
    static const double legacy[] = {500,700,900,1100,1200,1300,1400,1500,1600,1700,1900,2100,2300,2500,2700};
    const int count = (int)(sizeof(strength)/sizeof(strength[0]));
    if(requested <= strength[0]) return legacy[0];
    if(requested >= strength[count-1]) return legacy[count-1];
    int i=1; while(i<count && requested>strength[i]) ++i;
    double fraction=(requested-strength[i-1])/(strength[i]-strength[i-1]);
    return legacy[i-1]+fraction*(legacy[i]-legacy[i-1]);
}
