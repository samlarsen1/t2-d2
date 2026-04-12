package com.t2d2.app.ui.viewmodel

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.t2d2.app.data.models.Portfolio
import com.t2d2.app.data.models.Trade
import com.t2d2.app.data.repository.PortfolioRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class DashboardViewModel @Inject constructor(
    private val repository: PortfolioRepository,
) : ViewModel() {

    val portfolio: StateFlow<Portfolio?> = repository.portfolio
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    val recentTrades: StateFlow<List<Trade>> = repository.recentTrades
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private val _isLoading = MutableStateFlow(true)
    val isLoading: StateFlow<Boolean> = _isLoading.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _isLoading.value = true
            runCatching { repository.fetchPortfolio() }
            _isLoading.value = false
        }
    }
}
