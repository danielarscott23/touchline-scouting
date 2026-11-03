"""Theme the charts without changing their scales or statistical values."""
import altair as alt


def chart_theme(chart,dark=False):
    if not dark:
        return chart
    return (chart.encode(color=alt.Color("Player:N",legend=alt.Legend(orient="bottom",labelLimit=420),
                scale=alt.Scale(range=["#79baff","#c5dfff","#427fcb"])))
            .configure(background="#101827")
            .configure_axis(labelColor="#e5efff",titleColor="#f3f7ff",gridColor="#2b3b54",domainColor="#647a99",tickColor="#647a99")
            .configure_legend(labelColor="#e5efff",titleColor="#f3f7ff")
            .configure_view(stroke="transparent"))
